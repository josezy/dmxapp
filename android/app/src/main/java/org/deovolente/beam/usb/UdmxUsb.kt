package org.deovolente.beam.usb

import android.app.PendingIntent
import android.content.Context
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbManager
import org.deovolente.beam.engine.toUsbBytes

data class UsbHealth(
    var ok: Int = 0,
    var fail: Int = 0,
    var streak: Int = 0,
    var skipped: Int = 0,
    var lastError: String = "",
) {
    fun line(): String {
        val tail = if (streak > 0 && lastError.isNotEmpty()) "  ·  $lastError" else ""
        return "usb  ok $ok  fail $fail  racha $streak  saltos $skipped$tail"
    }
}

class UdmxUsb(context: Context) {
    private val app = context.applicationContext
    private val manager = app.getSystemService(Context.USB_SERVICE) as UsbManager
    private val lock = Any()
    private var device: UsbDevice? = null
    private var conn: UsbDeviceConnection? = null
    val health = UsbHealth()
    private var linkNext = 0.0

    fun find(): UsbDevice? =
        manager.deviceList.values.firstOrNull {
            it.vendorId == VID && it.productId == PID
        }

    fun hasPermission(device: UsbDevice): Boolean = manager.hasPermission(device)

    fun requestPermission(device: UsbDevice, pi: PendingIntent) {
        manager.requestPermission(device, pi)
    }

    fun open(dev: UsbDevice): Boolean =
        synchronized(lock) {
            closeLocked()
            val c = manager.openDevice(dev)
            if (c == null) {
                markDead("openDevice failed")
                return false
            }
            if (dev.interfaceCount > 0) {
                val intf = dev.getInterface(0)
                if (!c.claimInterface(intf, true)) {
                    c.close()
                    markDead("claimInterface failed")
                    return false
                }
            }
            device = dev
            conn = c
            resetStats()
            return true
        }

    fun close() = synchronized(lock) { closeLocked() }

    private fun closeLocked() {
        val c = conn
        val d = device
        if (c != null && d != null && d.interfaceCount > 0) {
            try {
                c.releaseInterface(d.getInterface(0))
            } catch (_: Exception) {
            }
        }
        try {
            c?.close()
        } catch (_: Exception) {
        }
        conn = null
        device = null
    }

    fun handleOk(): Boolean {
        val open = device ?: return false
        val found = find() ?: return false
        return found.deviceName == open.deviceName
    }

    fun linkCheckDue(now: Double, interval: Double = 1.0): Boolean {
        if (now < linkNext) return false
        linkNext = now + interval
        return true
    }

    fun isDead(threshold: Int = USB_DEAD_STREAK): Boolean = health.streak >= threshold

    fun markDead(reason: String) {
        health.streak = USB_DEAD_STREAK
        health.fail += 1
        health.lastError = reason
    }

    fun noteSkip(n: Int) {
        if (n > 0) health.skipped += n
    }

    fun sendRangeOnce(startIndex: Int, values: IntArray, timeoutMs: Int = 25): Boolean =
        synchronized(lock) {
            val c = conn ?: run {
                noteFail("no connection")
                return false
            }
            val payload = toUsbBytes(values)
            return try {
                val sent =
                    c.controlTransfer(
                        BM_REQUEST,
                        CMD_SET_RANGE,
                        payload.size,
                        startIndex,
                        payload,
                        payload.size,
                        timeoutMs,
                    )
                if (sent < 0) {
                    noteFail("controlTransfer $sent")
                    false
                } else {
                    noteOk()
                    true
                }
            } catch (e: Exception) {
                noteFail(e.message ?: e.toString())
                false
            }
        }

    fun sendRange(
        startIndex: Int,
        values: IntArray,
        retries: Int = 3,
        timeoutMs: Int = 80,
    ): Boolean {
        val attempts = retries.coerceAtLeast(1)
        repeat(attempts) { i ->
            if (sendRangeOnce(startIndex, values, timeoutMs)) return true
            if (i + 1 < attempts) Thread.sleep(30)
        }
        return false
    }

    private fun resetStats() {
        health.ok = 0
        health.fail = 0
        health.streak = 0
        health.skipped = 0
        health.lastError = ""
        linkNext = System.nanoTime() / 1_000_000_000.0 + 1.0
    }

    private fun noteOk() {
        health.ok += 1
        health.streak = 0
    }

    private fun noteFail(reason: String) {
        health.fail += 1
        health.streak += 1
        health.lastError = reason
    }

    companion object {
        const val VID = 0x16C0
        const val PID = 0x05DC
        const val CMD_SET_RANGE = 2
        const val BM_REQUEST = UsbConstants.USB_TYPE_VENDOR or UsbConstants.USB_DIR_OUT
        const val USB_DEAD_STREAK = 20
        const val START_INDEX = 0
        const val ACTION_USB_PERMISSION = "org.deovolente.beam.USB_PERMISSION"
    }
}
