package dev.friday.companion

import android.Manifest
import android.app.NotificationManager
import android.content.*
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import androidx.core.content.ContextCompat
import dev.friday.core.Protocol
import kotlinx.serialization.json.*

fun safeLabel(value: String, fallback: String = "unknown", limit: Int = 120) = value.filter { !it.isISOControl() }.take(limit).ifBlank { fallback }
fun Context.granted(permission: String) = ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

object SystemSignals {
    fun battery(context: Context): JsonObject? {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return null
        val charging = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
        return buildJsonObject { put("level", (level * 100 / scale).coerceIn(0, 100)); put("charging", charging) }
    }
    fun ssidHash(context: Context): String? {
        if (!context.granted(Manifest.permission.ACCESS_FINE_LOCATION)) return null
        @Suppress("DEPRECATION") val ssid = (context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager).connectionInfo?.ssid
        if (ssid.isNullOrBlank() || ssid == WifiManager.UNKNOWN_SSID) return null
        return Protocol.hex(Protocol.sha256((context.repository.settings.salt + ":" + ssid.trim('"')).toByteArray(Charsets.UTF_8)))
    }
    fun network(context: Context): JsonObject {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val caps = manager.getNetworkCapabilities(manager.activeNetwork)
        val transport = when {
            caps == null -> "offline"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
            else -> "other"
        }
        val hash = if (transport == "wifi" && context.repository.settings.homeHash.isNotEmpty()) ssidHash(context) else null
        return buildJsonObject {
            put("transport", transport); put("home", hash != null && hash == context.repository.settings.homeHash)
            if (hash != null) put("ssid_hash", hash)
        }
    }
}

class SystemCollector(private val context: Context, private val repo: Repository) {
    private var unlocks = 0
    private val last = mutableMapOf<String, JsonObject>()
    private fun changed(signal: String, important: Boolean = false, read: () -> JsonObject?) {
        if (!repo.settings.active(signal)) { last.remove(signal); return }
        val payload = read() ?: return
        if (last[signal] != payload) { last[signal] = payload; repo.record(signal, important) { payload } }
    }
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (repo.settings.active("screen")) {
                val state = when (intent.action) { Intent.ACTION_SCREEN_ON -> "on"; Intent.ACTION_SCREEN_OFF -> "off"; Intent.ACTION_USER_PRESENT -> "unlocked"; else -> null }
                if (state != null) {
                    if (state == "unlocked") unlocks++
                    repo.record("screen", true) { buildJsonObject { put("state", state); put("unlock_count", unlocks) } }
                }
            }
            if (intent.action == Intent.ACTION_SCREEN_OFF) repo.scope.launchUsageFlush()
        }
    }
    private fun kotlinx.coroutines.CoroutineScope.launchUsageFlush() { usage.screenOff() }
    val usage = UsageCollector(context, repo)
    private val audio = context.getSystemService(AudioManager::class.java)
    private val callback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = devices(added, true)
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = devices(removed, false)
    }
    private fun devices(devices: Array<out AudioDeviceInfo>, connected: Boolean) {
        if (!repo.settings.active("audio_devices")) return
        devices.filter { it.isSink }.forEach { device ->
            val kind = when (device.type) {
                AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_USB_HEADSET -> "headphones"
                AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_BLE_SPEAKER -> "bluetooth"
                else -> return@forEach
            }
            if (kind == "bluetooth" && Build.VERSION.SDK_INT >= 31 && !context.granted(Manifest.permission.BLUETOOTH_CONNECT)) return@forEach
            repo.record("audio_devices", true) { buildJsonObject { put("kind", kind); put("label", safeLabel(device.productName.toString())); put("connected", connected) } }
        }
    }
    fun start() {
        ContextCompat.registerReceiver(context, receiver, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON); addAction(Intent.ACTION_SCREEN_OFF); addAction(Intent.ACTION_USER_PRESENT)
        }, ContextCompat.RECEIVER_NOT_EXPORTED)
        audio.registerAudioDeviceCallback(callback, android.os.Handler(android.os.Looper.getMainLooper()))
    }
    fun tick() {
        usage.poll()
        changed("battery") { SystemSignals.battery(context) }
        changed("network") { SystemSignals.network(context) }
        changed("interruption") { buildJsonObject {
            put("dnd", context.getSystemService(NotificationManager::class.java).currentInterruptionFilter)
            put("ringer", audio.ringerMode)
        } }
    }
    fun close() { context.unregisterReceiver(receiver); audio.unregisterAudioDeviceCallback(callback); usage.reset() }
}
