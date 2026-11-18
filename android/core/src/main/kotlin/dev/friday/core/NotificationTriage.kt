package dev.friday.core

import kotlinx.serialization.json.*

data class NotificationMetadata(val id: String, val app: String, val category: String,
                                val importance: Int, val ongoing: Boolean = false)
data class TriagePolicy(val situation: String, val until: Double, val vip: Set<String>,
                        val urgent: Set<String>, val snooze: Boolean, val blocked: Set<String>) {
    companion object {
        fun packages(values: JsonArray): Set<String> {
            require(values.size <= 30)
            return values.map { it.jsonPrimitive.content.also(::packageName) }.toSet()
        }
        fun packageName(value: String) {
            require(value.length in 3..200 && (value == "android" || value.matches(Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z0-9_]+)+"))))
        }
        fun parse(value: JsonObject, now: Double): TriagePolicy {
            require(value.keys.all { it in setOf("situation", "until", "vip", "urgent", "snooze", "blocked") })
            val situation = value.getValue("situation").jsonPrimitive.content
            val until = value.getValue("until").jsonPrimitive.double
            require(situation in setOf("study", "class", "sleep", "free"))
            require(until.isFinite() && until > now && until <= now + 120)
            return TriagePolicy(situation, until, packages(value.getValue("vip").jsonArray),
                packages(value.getValue("urgent").jsonArray), value.getValue("snooze").jsonPrimitive.boolean,
                packages(value["blocked"]?.jsonArray ?: JsonArray(emptyList())))
        }
    }
}

object NotificationSignals {
    fun identity(salt: String, key: String, posted: Long) = Protocol.hex(Protocol.sha256("$salt\u0000$key\u0000$posted".toByteArray(Charsets.UTF_8)))
    fun outcome(reason: Int) = when (reason) { 1 -> "opened"; 2, 3 -> "dismissed"; else -> "removed" }
    fun reason(value: Int) = value.coerceIn(0, 30)
}

/** Android owns timed restoration; this class never cancels or reposts another app's notification. */
class SnoozePolicy(private val clock: () -> Long = System::currentTimeMillis) {
    companion object { const val LEASE_MS = 10_000L }
    fun duration(meta: NotificationMetadata, policy: TriagePolicy?, enabled: Boolean, collecting: Boolean,
                 connected: Boolean, localVip: Set<String> = emptySet(), localUrgent: Set<String> = emptySet()): Long? {
        if (!enabled || !collecting || !connected || policy == null || !policy.snooze || clock() / 1000.0 >= policy.until) return null
        if (policy.situation !in setOf("study", "class") || meta.app !in policy.blocked) return null
        if (meta.ongoing || meta.importance >= 4 || meta.app in setOf("android", "com.android.systemui") ||
            meta.category in setOf("call", "alarm", "missed_call", "voicemail")) return null
        if (meta.app in policy.vip || meta.app in policy.urgent || meta.app in localVip || meta.app in localUrgent) return null
        return minOf(LEASE_MS, ((policy.until - clock() / 1000.0) * 1000).toLong()).takeIf { it > 0 }
    }
}

data class ModeRequest(val mode: String, val value: Int, val token: String, val until: Double, val restore: Boolean) {
    companion object {
        fun parse(value: JsonObject, now: Double): ModeRequest {
            require(value.keys.all { it in setOf("mode", "value", "token", "until", "restore") })
            val mode = value.getValue("mode").jsonPrimitive.content
            val target = value.getValue("value").jsonPrimitive.int
            val token = value.getValue("token").jsonPrimitive.content
            val until = value.getValue("until").jsonPrimitive.double
            val restore = value["restore"]?.jsonPrimitive?.boolean ?: false
            require(mode in setOf("dnd", "ringer") && target in if (mode == "dnd") 1..4 else 0..2)
            require(token.matches(Regex("[A-Za-z0-9_-]{16,80}")))
            require(until.isFinite() && until <= now + 86400 && (restore || until > now))
            return ModeRequest(mode, target, token, until, restore)
        }
    }
}

/** Compare before restoring so a manual owner change wins over a stale automation receipt. */
data class ModeLease(val token: String, val mode: String, val previous: Int, val applied: Int, val until: Double,
                     val previousDnd: Int? = null, val appliedDnd: Int? = null) {
    fun shouldRestore(now: Double, current: Int, forced: Boolean = false) = (forced || now >= until) && current == applied
    fun preservesDnd(current: Int) = mode != "ringer" || previousDnd == null || current == (appliedDnd ?: previousDnd)
}
