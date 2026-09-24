package org.deovolente.beam

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.usb.UsbDevice
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.deovolente.beam.engine.FrameMaker
import org.deovolente.beam.engine.Rig
import org.deovolente.beam.engine.ShowCatalog
import org.deovolente.beam.engine.ShowPlayer
import org.deovolente.beam.engine.blackoutBuffer
import org.deovolente.beam.engine.buildRig
import org.deovolente.beam.engine.loadCatalog
import org.deovolente.beam.engine.nowPerf
import org.deovolente.beam.engine.pump
import org.deovolente.beam.usb.UdmxUsb
import org.json.JSONObject

data class PadState(
    val line: String = "abriendo uDMX…",
    val scene: String? = null,
    val usb: String = "usb —",
)

class DmxService : Service() {
    inner class LocalBinder : Binder() {
        fun service(): DmxService = this@DmxService
    }

    private val binder = LocalBinder()
    private val _state = AtomicReference(PadState())
    fun snapshot(): PadState = _state.get()

    lateinit var usb: UdmxUsb
        private set

    private lateinit var catalog: ShowCatalog
    private lateinit var beamSequences: Map<String, JSONObject>
    private lateinit var lpcSequences: Map<String, JSONObject>
    var rig: Rig = buildRig(0, 2)
        private set
    private val jobs = LinkedBlockingQueue<Job>()
    private val stop = AtomicBoolean(false)
    private val running = AtomicBoolean(true)
    private var worker: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var lastScene: Job? = null
    private var lastFrame: IntArray? = null
    private var lastPose: List<Pair<Double, Double>> = emptyList()
    private var nextRecoverAt = 0.0

    sealed class Job {
        data class Play(val name: String, val paletteId: String, val speedId: String) : Job()

        data class SetRig(val nLpc: Int, val nBeam: Int, val order: String) : Job()

        data object Blackout : Job()

        data object Reconnect : Job()

        data object Quit : Job()
    }

    override fun onCreate() {
        super.onCreate()
        usb = UdmxUsb(this)
        catalog =
            loadCatalog(
                assets.open("show/looks.json").bufferedReader().use { it.readText() },
                assets.open("show/palettes.json").bufferedReader().use { it.readText() },
            )
        beamSequences = loadJsonDir("sequences")
        lpcSequences = loadJsonDir("lpc-sequences")
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock =
            pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "deo:dmx").apply { setReferenceCounted(false) }
        createChannel()
        val notif = buildNotif(snapshot().line)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIF_ID, notif)
        }
        worker = Thread(this::loop, "dmx-worker").also { it.start() }
        tryOpen("show · uDMX listo")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_BLACKOUT -> blackout()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onDestroy() {
        submit(Job.Quit)
        worker?.join(1500)
        blackoutNow()
        usb.close()
        wakeLock?.release()
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        submit(Job.Quit)
        stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    fun play(name: String, paletteId: String, speedId: String) {
        if (name !in catalog.looks) return
        if (paletteId !in catalog.paletteById || speedId !in catalog.speedById) return
        submit(Job.Play(name, paletteId, speedId))
    }

    fun setRig(nLpc: Int, nBeam: Int, order: String) {
        submit(Job.SetRig(nLpc, nBeam, order))
    }

    fun blackout() = submit(Job.Blackout)

    fun reconnect() = submit(Job.Reconnect)

    fun attachDevice(device: UsbDevice) {
        if (usb.hasPermission(device)) {
            submit(Job.Reconnect)
        }
    }

    private fun submit(job: Job) {
        if (job is Job.Play || job is Job.Blackout) lastScene = job
        stop.set(true)
        jobs.clear()
        jobs.offer(job)
    }

    private fun emit(line: String, scene: String? = snapshot().scene) {
        val next = PadState(line = line, scene = scene, usb = usb.health.line())
        _state.set(next)
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, buildNotif(line))
    }

    private fun tryOpen(okMsg: String): Boolean {
        val dev = usb.find()
        if (dev == null) {
            emit("uDMX: no encontrado (vid=0x16c0 pid=0x05dc). OTG + QLC+ cerrado.")
            return false
        }
        if (!usb.hasPermission(dev)) {
            emit("uDMX: sin permiso USB")
            return false
        }
        return if (usb.open(dev)) {
            emit(okMsg)
            true
        } else {
            emit("uDMX: no se pudo abrir")
            false
        }
    }

    private fun reconnectUsb(): Boolean {
        usb.close()
        return tryOpen("show · uDMX reconectado")
    }

    private fun restoreLast() {
        val scene = lastScene ?: return
        if (jobs.isNotEmpty()) return
        if (scene is Job.Play) {
            jobs.offer(scene)
            return
        }
        if (scene is Job.Blackout) {
            blackoutNow()
            emit("blackout", "blackout")
        }
    }

    private fun reconnectAndRestore(reason: String) {
        val now = nowPerf()
        val wait = nextRecoverAt - now
        if (wait > 0) {
            try {
                Thread.sleep((wait * 1000).toLong().coerceAtLeast(1L))
            } catch (_: InterruptedException) {
                return
            }
        }
        emit("$reason · reconectando…")
        val ok = reconnectUsb()
        nextRecoverAt = nowPerf() + HEARTBEAT_S
        if (ok) restoreLast()
    }

    private fun heartbeat() {
        if (!usb.handleOk()) {
            reconnectAndRestore("uDMX perdido")
            return
        }
        val scene = lastScene ?: return
        if (scene is Job.Play) {
            if (jobs.isEmpty()) jobs.offer(scene)
            return
        }
        val frame = lastFrame
        val keep =
            if (frame != null) usb.sendRangeOnce(UdmxUsb.START_INDEX, frame) else true
        if (!keep || usb.isDead()) reconnectAndRestore("uDMX perdido")
    }

    private fun blackoutNow() {
        val frame = blackoutBuffer(rig)
        if (frame.isNotEmpty()) usb.sendRange(UdmxUsb.START_INDEX, frame)
        lastFrame = frame
    }

    private fun linkDead(): Boolean {
        if (usb.linkCheckDue(nowPerf()) && !usb.handleOk()) {
            usb.markDead("No such device")
            return true
        }
        return usb.isDead()
    }

    private fun loop() {
        wakeLock?.acquire()
        while (running.get()) {
            val job =
                try {
                    jobs.poll((HEARTBEAT_S * 1000).toLong(), TimeUnit.MILLISECONDS)
                } catch (_: InterruptedException) {
                    continue
                }
            if (job == null) {
                heartbeat()
                continue
            }
            stop.set(false)
            when (job) {
                Job.Quit -> {
                    running.set(false)
                    blackoutNow()
                    emit("blackout", "blackout")
                    return
                }
                Job.Reconnect -> reconnectAndRestore("reconectando uDMX")
                is Job.SetRig -> {
                    rig = buildRig(job.nLpc, job.nBeam, job.order)
                    lastPose = emptyList()
                    blackoutNow()
                    val labels = rig.fixtures.joinToString("  ") { it.label }.ifEmpty { "vacío" }
                    emit(labels, null)
                }
                Job.Blackout, is Job.Play -> {
                    val stale = usb.isDead() || !usb.handleOk() || usb.find() == null
                    if (stale) reconnectUsb()
                    if (usb.find() == null || !usb.handleOk()) {
                        emit("sin uDMX · reintento en 1 s")
                        continue
                    }
                    if (job is Job.Blackout) {
                        blackoutNow()
                        emit("blackout", "blackout")
                    } else if (job is Job.Play) {
                        playLook(job)
                    }
                }
            }
        }
    }

    private fun playLook(job: Job.Play) {
        val look = catalog.looks[job.name]
        val palette = catalog.paletteById[job.paletteId]
        val scale = catalog.speedById[job.speedId]
        if (look == null || palette == null || scale == null) {
            emit("look, paleta o velocidad desconocida")
            return
        }
        if (rig.span <= 0) {
            emit("elige al menos un fixture")
            return
        }
        val player =
            try {
                ShowPlayer(rig, look, palette, scale, beamSequences, lpcSequences, lastPose)
            } catch (exc: Exception) {
                emit("error: ${exc.message}")
                return
            }
        val speedLabel = catalog.speeds.first { it.id == job.speedId }.label
        emit("${look.label} · ${palette.label} · $speedLabel", job.name)
        val stats =
            pump(
                fps = player.fps,
                stop = stop,
                sendOnce = { frame ->
                    val ok = usb.sendRangeOnce(UdmxUsb.START_INDEX, frame)
                    if (ok) {
                        lastFrame = frame
                        lastPose = player.lastPose.toList()
                    }
                    ok
                },
                isDead = { linkDead() },
                make = FrameMaker { t, now -> player.frame(now, t) },
                onSkip = { usb.noteSkip(it) },
            )
        if (stats.usbDead) {
            val err = usb.health.lastError.ifEmpty { "overflow/timeout" }
            reconnectAndRestore("uDMX saturado ($err)")
        }
    }

    private fun loadJsonDir(dir: String): Map<String, JSONObject> {
        val files = assets.list(dir)?.filter { it.endsWith(".json") } ?: emptyList()
        return files.associate { file ->
            val name = file.removeSuffix(".json")
            val text = assets.open("$dir/$file").bufferedReader().use { it.readText() }
            name to JSONObject(text)
        }
    }

    private fun createChannel() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW),
        )
    }

    private fun buildNotif(line: String): Notification {
        val open =
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        val blackout =
            PendingIntent.getService(
                this,
                1,
                Intent(this, DmxService::class.java).setAction(ACTION_BLACKOUT),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(line)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(0, getString(R.string.blackout), blackout).build())
            .build()
    }

    companion object {
        const val CHANNEL_ID = "dmx"
        const val NOTIF_ID = 17
        const val ACTION_BLACKOUT = "org.deovolente.beam.BLACKOUT"
        const val HEARTBEAT_S = 1.0
    }
}
