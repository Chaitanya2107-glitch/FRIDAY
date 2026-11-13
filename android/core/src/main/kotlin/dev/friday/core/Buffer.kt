package dev.friday.core

import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

val SIGNALS = setOf("app_usage", "screen", "battery", "network", "motion", "places", "audio_devices", "media", "notifications", "sleep", "steps", "interruption")

@Serializable data class PhoneEvent(val id: String, val timestamp: Double, val type: String, val payload: JsonObject)
data class BufferedEvent(val event: PhoneEvent, val sentAt: Long = 0)

interface BufferStore {
    fun rows(): List<BufferedEvent>
    fun put(row: BufferedEvent)
    fun delete(ids: List<String>)
    fun clear()
    fun <T> transaction(block: () -> T): T
}

interface SharingPolicy {
    fun enabled(signal: String): Boolean
    fun pausedUntil(): Long
    fun retentionDays(): Int
    fun forgetting(): Boolean
}

class EventBuffer(private val store: BufferStore, private val clock: () -> Long) {
    @Synchronized fun add(type: String, payload: JsonObject, policy: SharingPolicy): PhoneEvent? {
        if (type !in SIGNALS || !policy.enabled(type) || clock() < policy.pausedUntil() || policy.forgetting()) return null
        val event = PhoneEvent(UUID.randomUUID().toString(), clock() / 1000.0, type, payload)
        require(payload.toString().toByteArray(Charsets.UTF_8).size <= 2048)
        store.transaction { store.put(BufferedEvent(event)); prune(policy.retentionDays()) }
        return event
    }
    @Synchronized fun prune(days: Int) = store.transaction {
        val cutoff = clock() - days.coerceIn(1, 7) * 86400000L
        val rows = store.rows().sortedBy { it.event.timestamp }
        store.delete(rows.filter { it.event.timestamp * 1000 < cutoff }.map { it.event.id })
        val remaining = store.rows().sortedBy { it.event.timestamp }
        store.delete(remaining.take((remaining.size - 5000).coerceAtLeast(0)).map { it.event.id })
    }
    @Synchronized fun pending(max: Int = 40): List<PhoneEvent> = store.rows().filter { it.sentAt == 0L }.sortedBy { it.event.timestamp }.take(max).map { it.event }
    @Synchronized fun acknowledge(ids: Set<String>) = store.transaction {
        store.rows().filter { it.event.id in ids }.forEach { store.put(it.copy(sentAt = clock())) }
    }
    @Synchronized fun sentLastHour(): List<BufferedEvent> = store.rows().filter { it.sentAt >= clock() - 3600000 && it.sentAt > 0 }
    @Synchronized fun discardSignal(type: String) = store.transaction { store.delete(store.rows().filter { it.event.type == type && it.sentAt == 0L }.map { it.event.id }) }
    @Synchronized fun clear() = store.transaction { store.clear() }
}

class CollectorGate(private val policy: SharingPolicy, private val buffer: EventBuffer, private val clock: () -> Long) {
    fun collect(signal: String, read: () -> JsonObject): PhoneEvent? {
        if (signal !in SIGNALS || !policy.enabled(signal) || policy.forgetting() || clock() < policy.pausedUntil()) return null
        return buffer.add(signal, read(), policy)
    }
}
