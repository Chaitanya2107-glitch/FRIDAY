package dev.friday.core

import java.io.IOException
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

fun interface RequestKey { fun sign(bytes: ByteArray): ByteArray }
data class SignedReply(val body: JsonObject, val nonce: String)

class SignedClient(origin: String, private val id: String, private val key: RequestKey,
                   client: OkHttpClient = OkHttpClient(), private val clock: () -> Long = System::currentTimeMillis) {
    companion object {
        private val pacing = java.util.concurrent.ConcurrentHashMap<String, Long>()
        private fun pace(id: String) = synchronized(pacing) {
            val remaining = (pacing[id] ?: 0L) - System.nanoTime()
            if (remaining > 0) java.util.concurrent.TimeUnit.NANOSECONDS.sleep(remaining)
            pacing[id] = System.nanoTime() + 2_500_000_000L
        }
    }
    val origin = PairingGrant.origin(origin)
    private val http = client.newBuilder().followRedirects(false).followSslRedirects(false)
        .callTimeout(java.time.Duration.ofSeconds(40)).readTimeout(java.time.Duration.ofSeconds(38)).build()
    fun json(method: String, operation: String, body: JsonObject? = null): SignedReply {
        require(operation.matches(Regex("[a-z/]+")) && !operation.contains("//"))
        val raw = body?.toString()?.toByteArray(Charsets.UTF_8) ?: byteArrayOf()
        require(raw.size <= 16384) { "Batch exceeds P0 request cap" }
        pace(id) // All clients for this key share P0's 30-request/minute allowance.
        val nonce = Protocol.nonce(); val timestamp = (clock() / 1000).toString()
        val signature = key.sign(Protocol.canonical(method, "/remote/v1/$operation", raw, timestamp, nonce))
        val request = Request.Builder().url("$origin/v1/$operation")
            .header("X-Device-Id", id).header("X-Timestamp", timestamp).header("X-Nonce", nonce)
            .header("X-Signature", Protocol.b64(signature)).header("Content-Type", "application/json")
            .method(method, if (method == "GET") null else raw.toRequestBody("application/json".toMediaType())).build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                if (response.code in 400..499) throw RequestRefused(response.code)
                throw IOException("Laptop unavailable (${response.code})")
            }
            val source = response.body?.source() ?: throw IOException("Empty laptop response")
            if (source.request(262145)) throw IOException("Oversized laptop response")
            return SignedReply(Json.parseToJsonElement(source.readUtf8()).jsonObject, nonce)
        }
    }
}

fun eventJson(event: PhoneEvent): JsonObject = Json.parseToJsonElement(Json.encodeToString(event)).jsonObject

class BatchSender(private val buffer: EventBuffer, private val client: SignedClient) {
    fun send(generation: Int): Int {
        var rows = buffer.pending()
        if (rows.isEmpty()) return 0
        fun body() = buildJsonObject { put("generation", generation); put("events", JsonArray(rows.map(::eventJson))) }
        while (body().toString().toByteArray(Charsets.UTF_8).size > 15000 && rows.size > 1) rows = rows.take(rows.size / 2)
        val reply = client.json("POST", "phone/events", body()).body
        val acknowledged = reply.getValue("acknowledged").jsonArray.map { it.jsonPrimitive.content }.toSet()
        require(acknowledged.all { id -> rows.any { it.id == id } }) { "Unknown acknowledgement" }
        buffer.acknowledge(acknowledged)
        return acknowledged.size
    }
}
