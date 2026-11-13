package dev.friday.companion

import android.content.Context
import dev.friday.core.*
import kotlinx.serialization.json.*
import java.security.SecureRandom

class Settings(context: Context) : SharingPolicy {
    private val prefs = context.getSharedPreferences("private", Context.MODE_PRIVATE)
    override fun enabled(signal: String) = prefs.getBoolean("signal.$signal", false)
    override fun pausedUntil() = prefs.getLong("pause", 0)
    override fun retentionDays() = prefs.getInt("retention", 7).coerceIn(1, 7)
    override fun forgetting() = prefs.getBoolean("forgetting", false)
    fun enabledSignals() = SIGNALS.filter(::enabled)
    fun active(signal: String) = enabled(signal) && !forgetting() && System.currentTimeMillis() >= pausedUntil()
    fun toggle(signal: String, on: Boolean) { require(signal in SIGNALS); check(prefs.edit().putBoolean("signal.$signal", on).commit()) }
    fun pauseHour() { check(prefs.edit().putLong("pause", System.currentTimeMillis() + 3600000).commit()) }
    fun resume() { check(prefs.edit().putLong("pause", 0).commit()) }
    fun retention(days: Int) { require(days in 1..7); check(prefs.edit().putInt("retention", days).commit()) }
    var origin: String
        get() = prefs.getString("origin", "")!!
        set(value) { check(prefs.edit().putString("origin", value).commit()) }
    var paired: Boolean
        get() = prefs.getBoolean("paired", false)
        set(value) { check(prefs.edit().putBoolean("paired", value).commit()) }
    var fingerprint: String
        get() = prefs.getString("fingerprint", "")!!
        set(value) { check(prefs.edit().putString("fingerprint", value).commit()) }
    var generation: Int
        get() = prefs.getInt("generation", 0)
        set(value) { check(prefs.edit().putInt("generation", value).commit()) }
    var lastSync: Long
        get() = prefs.getLong("lastSync", 0)
        set(value) { check(prefs.edit().putLong("lastSync", value).commit()) }
    var forgettingPending: Boolean
        get() = forgetting()
        set(value) { check(prefs.edit().putBoolean("forgetting", value).commit()) }
    var homeHash: String
        get() = prefs.getString("homeHash", "")!!
        set(value) { check(prefs.edit().putString("homeHash", value).commit()) }
    val salt: String get() = prefs.getString("salt", null) ?: Protocol.b64(ByteArray(32).also { SecureRandom().nextBytes(it) }).also { check(prefs.edit().putString("salt", it).commit()) }
    var places: JsonArray
        get() = Json.parseToJsonElement(prefs.getString("places", "[]")!!).jsonArray
        set(value) { check(prefs.edit().putString("places", value.toString()).commit()) }
    var contentApps: Set<String>
        get() = prefs.getStringSet("contentApps", emptySet())!!.toSet()
        set(value) { check(prefs.edit().putStringSet("contentApps", value).commit()) }
}
