package org.deovolente.beam

import android.Manifest
import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.deovolente.beam.engine.ShowCatalog
import org.deovolente.beam.engine.buildRig
import org.deovolente.beam.engine.loadCatalog
import org.deovolente.beam.usb.UdmxUsb

class MainActivity : Activity() {
    private var bound = false
    private var service: DmxService? = null
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var catalog: ShowCatalog
    private lateinit var home: LinearLayout
    private lateinit var pad: LinearLayout
    private lateinit var mapLine: TextView
    private lateinit var nLpcLabel: TextView
    private lateinit var nBeamLabel: TextView
    private lateinit var subtitle: TextView
    private lateinit var usbLine: TextView
    private lateinit var statusLine: TextView
    private val paletteButtons = mutableMapOf<String, Button>()
    private val speedButtons = mutableMapOf<String, Button>()
    private val lookButtons = mutableMapOf<String, Button>()
    private val orderButtons = mutableMapOf<String, Button>()
    private var nLpc = 0
    private var nBeam = 2
    private var order = "lpc_first"
    private var tunePalette = "blanco"
    private var tuneSpeed = "medio"
    private var activeLook: String? = null
    private var lastLine: String? = null

    private val conn =
        object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
                service = (binder as DmxService.LocalBinder).service()
                bound = true
                service?.setRig(nLpc, nBeam, order)
                maybeRequestUsb()
                paintStatus(service?.snapshot() ?: PadState())
            }

            override fun onServiceDisconnected(name: ComponentName?) {
                bound = false
                service = null
            }
        }

    private val usbReceiver =
        object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                if (intent.action != UdmxUsb.ACTION_USB_PERMISSION) return
                val device =
                    if (Build.VERSION.SDK_INT >= 33) {
                        intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
                    }
                val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                if (granted && device != null) service?.attachDevice(device)
            }
        }

    private val tick =
        object : Runnable {
            override fun run() {
                val snap = service?.snapshot()
                if (snap != null && snap.line != lastLine) paintStatus(snap)
                handler.postDelayed(this, 200)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        catalog =
            loadCatalog(
                assets.open("show/looks.json").bufferedReader().use { it.readText() },
                assets.open("show/palettes.json").bufferedReader().use { it.readText() },
            )
        loadStore()
        setContentView(buildUi())
        paintHome()
        paintSelection()
        val filter = IntentFilter(UdmxUsb.ACTION_USB_PERMISSION)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(usbReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(usbReceiver, filter)
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 0)
        }
        val start = Intent(this, DmxService::class.java)
        startForegroundService(start)
        bindService(start, conn, BIND_AUTO_CREATE)
        handleUsbIntent(intent)
        handler.post(tick)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleUsbIntent(intent)
    }

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        unregisterReceiver(usbReceiver)
        if (bound) {
            unbindService(conn)
            bound = false
        }
        super.onDestroy()
    }

    private fun handleUsbIntent(intent: Intent) {
        val device =
            if (Build.VERSION.SDK_INT >= 33) {
                intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
            }
        if (device != null) maybeRequestUsb(device)
    }

    private fun maybeRequestUsb(preferred: UsbDevice? = null) {
        val usb = service?.usb ?: UdmxUsb(this)
        val device = preferred ?: usb.find() ?: return
        if (usb.hasPermission(device)) {
            service?.attachDevice(device)
            return
        }
        val pi =
            PendingIntent.getBroadcast(
                this,
                0,
                Intent(UdmxUsb.ACTION_USB_PERMISSION).setPackage(packageName),
                PendingIntent.FLAG_MUTABLE,
            )
        usb.requestPermission(device, pi)
    }

    private fun dp(n: Int): Int = (n * resources.displayMetrics.density).toInt()

    private fun loadStore() {
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        nLpc = prefs.getInt("nLpc", 0)
        nBeam = prefs.getInt("nBeam", 2)
        order = prefs.getString("order", "lpc_first") ?: "lpc_first"
        tunePalette = prefs.getString("palette", "blanco") ?: "blanco"
        tuneSpeed = prefs.getString("speed", "medio") ?: "medio"
        if (tunePalette !in catalog.paletteById) tunePalette = "blanco"
        if (tuneSpeed !in catalog.speedById) tuneSpeed = "medio"
    }

    private fun saveStore() {
        getSharedPreferences(PREFS, MODE_PRIVATE)
            .edit()
            .putInt("nLpc", nLpc)
            .putInt("nBeam", nBeam)
            .putString("order", order)
            .putString("palette", tunePalette)
            .putString("speed", tuneSpeed)
            .apply()
    }

    private fun buildUi(): ScrollView {
        val root =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundColor(BG)
                setPadding(dp(14), dp(12), dp(14), dp(12))
            }
        home = buildHome()
        pad = buildPad()
        pad.visibility = View.GONE
        root.addView(home)
        root.addView(pad)
        return ScrollView(this).apply {
            setBackgroundColor(BG)
            addView(root)
        }
    }

    private fun buildHome(): LinearLayout {
        val box =
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
            }
        box.addView(title("Rig", 18f, FG))
        box.addView(
            muted(
                "LPC008 es el PAR de 7 canales. BEAM 60W es 30 canales. Las direcciones salen desde el canal 1.",
            ),
        )
        nLpcLabel = TextView(this)
        nBeamLabel = TextView(this)
        box.addView(stepper("LPC008 · 7CH", nLpcLabel, { bumpLpc(-1) }, { bumpLpc(1) }))
        box.addView(stepper("BEAM 60W · 30CH", nBeamLabel, { bumpBeam(-1) }, { bumpBeam(1) }))
        val orders = row()
        orders.addView(orderButton("PAR primero", "lpc_first"), weight())
        orders.addView(orderButton("BEAM primero", "beam_first"), weight())
        box.addView(orders)
        mapLine = muted("—")
        box.addView(mapLine)
        val enter =
            Button(this).apply {
                text = "Entrar al pad"
                setTextColor(PAD_FG)
                setBackgroundColor(PAD_BG)
                setOnClickListener { enterPad() }
            }
        box.addView(enter)
        return box
    }

    private fun buildPad(): LinearLayout {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val header = row()
        subtitle = muted("show")
        header.addView(subtitle, weight())
        val edit =
            smallButton("Rig").apply {
                setOnClickListener {
                    showHome(true)
                    paintHome()
                }
            }
        header.addView(edit)
        box.addView(header)
        usbLine = muted("usb —")
        box.addView(usbLine)
        val bar = row()
        val blackout =
            Button(this).apply {
                text = "BLACKOUT"
                setTextColor(Color.WHITE)
                setBackgroundColor(Color.parseColor("#8B1A1A"))
                typeface = Typeface.DEFAULT_BOLD
                textSize = 16f
                setOnClickListener { service?.blackout() }
            }
        val reconnect =
            Button(this).apply {
                text = "Reconectar"
                setTextColor(PAD_FG)
                setBackgroundColor(PAD_BG)
                setOnClickListener { service?.reconnect() }
            }
        bar.addView(blackout, weight())
        bar.addView(reconnect, weight())
        box.addView(bar)
        statusLine =
            TextView(this).apply {
                text = "abriendo uDMX…"
                setTextColor(FG)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
                setPadding(0, 0, 0, dp(8))
            }
        box.addView(statusLine)
        box.addView(chipRow(catalog.palettes.map { it.id to it.label }, paletteButtons) { choosePalette(it) })
        box.addView(chipRow(catalog.speeds.map { it.id to it.label }, speedButtons) { chooseSpeed(it) })
        val cols = if (resources.displayMetrics.widthPixels / resources.displayMetrics.density >= 720) 4 else 2
        for (group in catalog.groups) {
            box.addView(muted(group.title))
            for (rowLooks in group.looks.chunked(cols)) {
                val line = row()
                for (look in rowLooks) {
                    val b =
                        Button(this).apply {
                            text = look.label
                            setTextColor(PAD_FG)
                            setBackgroundColor(PAD_BG)
                            setOnClickListener { play(look.id) }
                            gravity = Gravity.CENTER
                        }
                    lookButtons[look.id] = b
                    line.addView(b, weight())
                }
                repeat(cols - rowLooks.size) { line.addView(TextView(this), weight()) }
                box.addView(line)
            }
        }
        return box
    }

    private fun chipRow(
        items: List<Pair<String, String>>,
        into: MutableMap<String, Button>,
        onClick: (String) -> Unit,
    ): HorizontalScrollView {
        val line = row()
        for ((id, label) in items) {
            val b =
                smallButton(label).apply {
                    val pal = catalog.paletteById[id]
                    if (pal != null) {
                        val cols =
                            pal.colors.map { Color.rgb(it.parRgb()[0], it.parRgb()[1], it.parRgb()[2]) }.toIntArray()
                        val swatch =
                            GradientDrawable(
                                GradientDrawable.Orientation.LEFT_RIGHT,
                                if (cols.size >= 2) cols else intArrayOf(cols[0], cols[0]),
                            )
                        swatch.setBounds(0, 0, dp(36), dp(10))
                        swatch.cornerRadius = dp(2).toFloat()
                        setCompoundDrawables(swatch, null, null, null)
                        compoundDrawablePadding = dp(6)
                    }
                    setOnClickListener { onClick(id) }
                }
            into[id] = b
            val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            lp.marginEnd = dp(6)
            line.addView(b, lp)
        }
        return HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            addView(line)
        }
    }

    private fun enterPad() {
        saveStore()
        service?.setRig(nLpc, nBeam, order)
        val rig = runCatching { buildRig(nLpc, nBeam, order) }.getOrNull()
        subtitle.text = rig?.fixtures?.joinToString(" ") { it.label }?.ifEmpty { "sin fixtures" } ?: "sin fixtures"
        showHome(false)
    }

    private fun play(id: String) {
        activeLook = id
        saveStore()
        paintSelection()
        service?.play(id, tunePalette, tuneSpeed)
    }

    private fun choosePalette(id: String) {
        tunePalette = id
        saveStore()
        paintSelection()
        val look = activeLook
        if (look != null) service?.play(look, tunePalette, tuneSpeed)
    }

    private fun chooseSpeed(id: String) {
        tuneSpeed = id
        saveStore()
        paintSelection()
        val look = activeLook
        if (look != null) service?.play(look, tunePalette, tuneSpeed)
    }

    private fun bumpLpc(delta: Int) {
        nLpc = (nLpc + delta).coerceIn(0, 8)
        paintHome()
    }

    private fun bumpBeam(delta: Int) {
        nBeam = (nBeam + delta).coerceIn(0, 8)
        paintHome()
    }

    private fun paintHome() {
        nLpcLabel.text = nLpc.toString()
        nBeamLabel.text = nBeam.toString()
        for ((id, btn) in orderButtons) mark(btn, id == order)
        val rig = runCatching { buildRig(nLpc, nBeam, order) }
        mapLine.text = rig.fold(
            { it.fixtures.joinToString("   ") { fx -> "${fx.type} ${fx.label}" }.ifEmpty { "ningún fixture" } },
            { it.message ?: "error" },
        )
    }

    private fun paintSelection() {
        for ((id, btn) in paletteButtons) mark(btn, id == tunePalette)
        for ((id, btn) in speedButtons) mark(btn, id == tuneSpeed)
        for ((id, btn) in lookButtons) mark(btn, id == activeLook)
    }

    private fun paintStatus(state: PadState) {
        lastLine = state.line
        if (::statusLine.isInitialized) statusLine.text = state.line
        if (::usbLine.isInitialized) usbLine.text = state.usb
    }

    private fun showHome(on: Boolean) {
        home.visibility = if (on) View.VISIBLE else View.GONE
        pad.visibility = if (on) View.GONE else View.VISIBLE
    }

    private fun mark(btn: Button, on: Boolean) {
        btn.setBackgroundColor(if (on) Color.WHITE else PAD_BG)
        btn.typeface = if (on) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
    }

    private fun orderButton(label: String, id: String): Button =
        smallButton(label).apply {
            orderButtons[id] = this
            setOnClickListener {
                order = id
                paintHome()
            }
        }

    private fun stepper(label: String, value: TextView, dec: () -> Unit, inc: () -> Unit): LinearLayout {
        val line = row()
        line.addView(TextView(this).apply {
            text = label
            setTextColor(FG)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        }, weight())
        val decBtn = smallButton("−").apply { setOnClickListener { dec() } }
        val incBtn = smallButton("+").apply { setOnClickListener { inc() } }
        value.setTextColor(FG)
        value.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
        value.gravity = Gravity.CENTER
        value.minWidth = dp(28)
        line.addView(decBtn)
        line.addView(value)
        line.addView(incBtn)
        return line
    }

    private fun smallButton(label: String): Button =
        Button(this).apply {
            text = label
            setTextColor(PAD_FG)
            setBackgroundColor(PAD_BG)
            textSize = 13f
            setPadding(dp(10), dp(8), dp(10), dp(8))
        }

    private fun title(text: String, sp: Float, color: Int): TextView =
        TextView(this).apply {
            this.text = text
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            setTypeface(typeface, Typeface.BOLD)
        }

    private fun muted(text: String): TextView =
        TextView(this).apply {
            this.text = text
            setTextColor(MUTED)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(0, dp(6), 0, dp(6))
        }

    private fun row(): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, dp(6))
        }

    private fun weight(): LinearLayout.LayoutParams {
        val lp = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        lp.marginEnd = dp(4)
        lp.marginStart = dp(4)
        lp.bottomMargin = dp(8)
        return lp
    }

    companion object {
        private const val PREFS = "deo.show"
        private val BG = Color.parseColor("#1A1A1A")
        private val FG = Color.parseColor("#ECECEC")
        private val MUTED = Color.parseColor("#8A8A8A")
        private val PAD_BG = Color.parseColor("#D8D8D8")
        private val PAD_FG = Color.parseColor("#111111")
    }
}
