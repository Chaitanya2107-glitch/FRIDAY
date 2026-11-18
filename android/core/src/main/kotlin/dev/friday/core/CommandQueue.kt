package dev.friday.core

import java.util.UUID
import kotlinx.serialization.json.*

data class WaitingCommand(val id: String, val created: Double, val expiresAt: Double,
                          val command: String, val args: JsonObject, val state: String = "waiting", val reply: JsonObject = buildJsonObject {})

interface CommandStore {
    fun rows(): List<WaitingCommand>
    fun put(row: WaitingCommand)
    fun remove(id: String)
}

/** Only commands independently checked as safe on the laptop may enter this queue. */
class CommandQueue(private val store: CommandStore, private val clock: () -> Long = System::currentTimeMillis) {
    private val draining = java.util.concurrent.atomic.AtomicBoolean(false)
    companion object {
        val SAFE = setOf("ring_laptop", "phone_handoff", "start_focus", "stop_focus", "set_scene", "add_note")
    }
    @Synchronized fun add(command: String, args: JsonObject, lifetimeSeconds: Int = 900): WaitingCommand {
        require(command in SAFE) { "Confirmation commands cannot be queued" }
        require(lifetimeSeconds in 1..86400)
        require(args.toString().toByteArray(Charsets.UTF_8).size <= 12000)
        require(store.rows().count { it.state == "waiting" } < 100) { "Command queue is full" }
        val now = clock() / 1000.0
        return WaitingCommand(UUID.randomUUID().toString(), now, now + lifetimeSeconds, command, args).also(store::put)
    }
    @Synchronized fun rows(): List<WaitingCommand> {
        store.rows().filter { it.state == "waiting" && it.expiresAt <= clock() / 1000.0 }
            .forEach { store.put(it.copy(state = "expired")) }
        return store.rows().sortedBy { it.created } // Stable sort retains durable enqueue order for equal timestamps.
    }
    @Synchronized fun dismiss(id: String) { store.remove(id) }
    private fun waiting(id: String): WaitingCommand? = synchronized(this) {
        rows().firstOrNull { it.id == id && it.state == "waiting" }
    }
    private fun receipt(id: String, state: String, reply: JsonObject = buildJsonObject {}) = synchronized(this) {
        // Cancellation removes the row; expiry changes its state. A late reply restores neither.
        waiting(id)?.let { store.put(it.copy(state = state, reply = reply)) }
    }
    fun drain(send: (JsonObject) -> JsonObject): Int {
        if (!draining.compareAndSet(false, true)) return 0
        try { return drainPending(send) } finally { draining.set(false) }
    }
    private fun drainPending(send: (JsonObject) -> JsonObject): Int {
        var count = 0
        for (id in rows().filter { it.state == "waiting" }.map { it.id }) {
            val row = waiting(id) ?: continue
            val body = buildJsonObject {
                put("id", row.id); put("created", row.created); put("expires_at", row.expiresAt)
                put("command", row.command); put("args", row.args)
            }
            try {
                val reply = send(body)
                val result = reply["result"]?.jsonPrimitive?.content ?: error("Missing queue receipt")
                receipt(row.id, when (result) { "uncertain" -> "uncertain"; "completed" -> "completed"; else -> "refused" }, reply["data"] as? JsonObject ?: buildJsonObject {})
                count++
            } catch (refused: RequestRefused) {
                receipt(row.id, "refused"); count++
            } catch (_: Exception) { break } // Preserve the same ID after a lost acknowledgement.
        }
        return count
    }
}

class RequestRefused(val status: Int) : java.io.IOException("Laptop refused request ($status)")

object TransferRules {
    const val MAX_SIZE = 100L * 1024 * 1024
    private val blocked = setOf("exe", "com", "bat", "cmd", "ps1", "psm1", "psd1", "msi", "msp", "scr", "lnk", "url", "vbs", "vbe", "js", "jse", "mjs", "cjs", "jar", "dll", "sys", "cpl", "hta", "wsf", "wsh", "sh", "bash", "zsh", "py", "pyw", "rb", "pl", "php", "apk", "aab", "dex", "so", "app", "dmg", "deb", "rpm", "reg", "scf", "desktop", "html", "htm", "svg", "chm", "iso", "img", "fish", "pkg", "webloc", "website", "inf", "gadget", "docm", "xlsm", "pptm", "xlam", "xll")
    fun name(value: String): String {
        require(value.isNotBlank() && value.length <= 160 && value == value.trim())
        require(value.none { it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() || it in "/\\:<>\"|?*" } && !value.startsWith('.') && !value.endsWith('.') && !value.endsWith(' '))
        val base = value.substringBefore('.').lowercase(java.util.Locale.ROOT)
        require(base !in setOf("con", "prn", "aux", "nul") && !base.matches(Regex("(?:com|lpt)[1-9]")))
        val extraBlocked = setOf("pif", "sct", "vb", "vba", "ws", "application", "appref-ms", "msix", "msixbundle", "appx", "appxbundle", "command", "workflow", "action", "scpt")
        require(value.split('.').drop(1).none { it.lowercase(java.util.Locale.ROOT) in blocked || it.lowercase(java.util.Locale.ROOT) in extraBlocked }) { "Executable and script files cannot be shared" }
        return value
    }
    fun link(text: String): String? = runCatching {
        val uri = java.net.URI(text.trim())
        text.trim().takeIf { uri.scheme?.lowercase(java.util.Locale.ROOT) in setOf("http", "https") && uri.host != null && uri.userInfo == null }
    }.getOrNull()
}
