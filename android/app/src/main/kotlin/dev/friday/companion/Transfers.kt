package dev.friday.companion

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import android.provider.OpenableColumns
import dev.friday.core.*
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID
import kotlinx.serialization.json.*

/** Files are opened only by a visible user action; no phone path is sent to the laptop. */
class Transfers(private val context: Context, private val repo: Repository) {
    private val prefs = context.getSharedPreferences("transfers", Context.MODE_PRIVATE)
    private val folder get() = File(context.filesDir, "handoff-uploads").apply { mkdirs() }
    companion object { private val lock = Any(); private val uploading = java.util.concurrent.atomic.AtomicBoolean(false) }
    private fun rows() = Json.parseToJsonElement(prefs.getString("waiting", "[]")!!).jsonArray.map { it.jsonObject }
    private fun save(rows: List<JsonObject>) { check(prefs.edit().putString("waiting", JsonArray(rows).toString()).commit()) }
    fun waiting(): List<JsonObject> = synchronized(lock) {
        val now = System.currentTimeMillis()
        val keep = rows().filter { it.getValue("expires_at").jsonPrimitive.double > now / 1000.0 }
        if (keep.size != rows().size) save(keep)
        val names = keep.map { it.getValue("local").jsonPrimitive.content }.toSet()
        folder.listFiles()?.filter { it.isFile && it.name !in names && it.lastModified() < now - 86400000 }?.forEach { it.delete() }
        keep
    }
    fun stage(uri: Uri) {
        check(repo.settings.paired && !repo.settings.forgetting())
        require(uri.scheme == "content") { "Share a file using Android's content picker" }
        var name = "shared-file"; var declaredSize = -1L
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) name = cursor.getString(nameIndex)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) declaredSize = cursor.getLong(sizeIndex)
            }
        }
        TransferRules.name(name)
        require(declaredSize <= TransferRules.MAX_SIZE) { "Maximum file size is 100 MB" }
        synchronized(lock) { require(rows().size < 2) { "Send or remove the two waiting files first" } }
        val local = UUID.randomUUID().toString(); val target = File(folder, local)
        val digest = MessageDigest.getInstance("SHA-256"); var size = 0L
        try {
            context.contentResolver.openInputStream(uri)!!.use { input -> target.outputStream().use { output ->
                val bytes = ByteArray(32768)
                while (true) {
                    val count = input.read(bytes); if (count < 0) break
                    check(!repo.settings.forgetting()); size += count
                    require(size <= TransferRules.MAX_SIZE) { "Maximum file size is 100 MB" }
                    digest.update(bytes, 0, count); output.write(bytes, 0, count)
                }
            } }
            synchronized(lock) {
                check(!repo.settings.forgetting()); require(rows().size < 2)
                save(rows() + buildJsonObject {
                    put("local", local); put("name", name); put("size", size); put("sha256", Protocol.hex(digest.digest()))
                    put("expires_at", System.currentTimeMillis() / 1000.0 + 86400)
                    put("id", ""); put("offset", 0)
                })
            }
            SharingService.scheduleSync(context)
        } catch (failure: Exception) { target.delete(); throw failure }
    }
    fun remove(local: String) = synchronized(lock) {
        require(local.matches(Regex("[a-f0-9-]{36}")))
        save(rows().filter { it.getValue("local").jsonPrimitive.content != local })
        File(folder, local).delete()
    }
    fun forget() = synchronized(lock) {
        save(emptyList())
        folder.listFiles()?.filter { it.isFile }?.forEach { it.delete() }
        prefs.getStringSet("downloads", emptySet())!!.forEach { runCatching { context.contentResolver.delete(Uri.parse(it), null, null) } }
        check(prefs.edit().remove("downloads").commit())
    }
    fun upload(maxChunks: Int = 20) {
        if (!uploading.compareAndSet(false, true)) return
        try { uploadPending(maxChunks) } finally { uploading.set(false) }
    }
    private fun uploadPending(maxChunks: Int) {
        var chunks = 0
        for (initial in waiting()) {
            val local = initial.getValue("local").jsonPrimitive.content
            if (initial.getValue("expires_at").jsonPrimitive.double <= System.currentTimeMillis() / 1000.0) { remove(local); continue }
            var row = initial
            fun persist(changes: Map<String, JsonElement>) {
                row = JsonObject(row + changes)
                synchronized(lock) {
                    check(!repo.settings.forgetting())
                    check(rows().any { it.getValue("local").jsonPrimitive.content == local })
                    save(rows().map { if (it.getValue("local").jsonPrimitive.content == local) row else it })
                }
            }
            try {
                check(!repo.settings.forgetting())
                if (row.getValue("id").jsonPrimitive.content.isEmpty()) {
                    val reply = repo.client().json("POST", "phone/file/begin", buildJsonObject {
                        put("name", row.getValue("name")); put("size", row.getValue("size")); put("sha256", row.getValue("sha256"))
                    }).body
                    persist(mapOf("id" to reply.getValue("id"), "offset" to (reply["offset"] ?: JsonPrimitive(0))))
                }
                val id = row.getValue("id").jsonPrimitive.content
                val size = row.getValue("size").jsonPrimitive.long
                RandomAccessFile(File(folder, local), "r").use { input ->
                    var offset = row.getValue("offset").jsonPrimitive.long
                    require(offset in 0..size); input.seek(offset)
                    while (offset < size) {
                        if (chunks++ >= maxChunks) return
                        check(!repo.settings.forgetting()); check(row.getValue("expires_at").jsonPrimitive.double > System.currentTimeMillis() / 1000.0)
                        check(System.currentTimeMillis() >= repo.settings.pausedUntil())
                        val bytes = ByteArray(minOf(10000L, size - offset).toInt()); input.readFully(bytes)
                        val reply = repo.client().json("POST", "phone/file/chunk", buildJsonObject { put("id", id); put("offset", offset); put("data", Protocol.b64(bytes)) }).body
                        val accepted = reply.getValue("offset").jsonPrimitive.long
                        require(accepted == offset + bytes.size)
                        offset = accepted; persist(mapOf("offset" to JsonPrimitive(offset)))
                        repo.message = "Sending file: $offset of $size bytes. P0 rate limits remain active."
                    }
                }
                val reply = repo.client().json("POST", "phone/file/finish", buildJsonObject { put("id", id) }).body
                require(reply.getValue("sha256") == row.getValue("sha256"))
                remove(local); repo.message = "File received in laptop quarantine. It was not opened."
            } catch (_: Exception) { repo.message = "File waiting on this phone. Reconnect to continue before its 24-hour expiry."; return }
        }
    }
    fun download(payload: JsonObject): Uri {
        val id = payload.getValue("id").jsonPrimitive.content
        val name = TransferRules.name(payload.getValue("name").jsonPrimitive.content)
        val size = payload.getValue("size").jsonPrimitive.long
        val sha = payload.getValue("sha256").jsonPrimitive.content
        require(size in 0..TransferRules.MAX_SIZE && sha.matches(Regex("[a-f0-9]{64}")))
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name); put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
            put(MediaStore.Downloads.RELATIVE_PATH, "Download/FRIDAY"); put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("Downloads unavailable")
        synchronized(lock) { check(prefs.edit().putStringSet("downloads", prefs.getStringSet("downloads", emptySet())!!.toSet() + uri.toString()).commit()) }
        try {
            val digest = MessageDigest.getInstance("SHA-256"); var offset = 0L
            context.contentResolver.openOutputStream(uri, "w")!!.use { output ->
                do {
                    check(!repo.settings.forgetting())
                    val reply = repo.client().json("POST", "phone/file/read", buildJsonObject { put("id", id); put("offset", offset) }).body
                    require(reply.getValue("offset").jsonPrimitive.long == offset)
                    require(reply.getValue("size").jsonPrimitive.long == size && reply.getValue("sha256").jsonPrimitive.content == sha && reply.getValue("name").jsonPrimitive.content == name)
                    val bytes = Protocol.decode(reply.getValue("data").jsonPrimitive.content)
                    require(bytes.size <= 10000 && offset + bytes.size <= size && (bytes.isNotEmpty() || offset == size))
                    check(!repo.settings.forgetting())
                    output.write(bytes); digest.update(bytes); offset += bytes.size
                    require(reply.getValue("done").jsonPrimitive.boolean == (offset == size))
                    repo.message = "Downloading: $offset of $size bytes. P0 rate limits remain active."
                } while (offset < size)
            }
            require(Protocol.hex(digest.digest()) == sha) { "File checksum mismatch" }
            check(!repo.settings.forgetting())
            context.contentResolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            synchronized(lock) { check(prefs.edit().putStringSet("downloads", prefs.getStringSet("downloads", emptySet())!!.toSet() - uri.toString()).commit()) }
            return uri
        } catch (failure: Exception) {
            context.contentResolver.delete(uri, null, null)
            synchronized(lock) { check(prefs.edit().putStringSet("downloads", prefs.getStringSet("downloads", emptySet())!!.toSet() - uri.toString()).commit()) }
            throw failure
        }
    }
}
