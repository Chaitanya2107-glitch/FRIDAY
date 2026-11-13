package dev.friday.core

import java.io.File
import java.security.KeyPairGenerator
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.net.ssl.SSLHandshakeException
import kotlin.test.*
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Test

class MemoryStore : BufferStore {
    val values = linkedMapOf<String, BufferedEvent>()
    override fun rows() = values.values.toList()
    override fun put(row: BufferedEvent) { values[row.event.id] = row }
    override fun delete(ids: List<String>) { ids.forEach(values::remove) }
    override fun clear() = values.clear()
    override fun <T> transaction(block: () -> T) = synchronized(this) { block() }
}
class Policy : SharingPolicy {
    var on = false; var pause = 0L; var forget = false
    override fun enabled(signal: String) = on
    override fun pausedUntil() = pause
    override fun retentionDays() = 7
    override fun forgetting() = forget
}
class CoreTest {
    @Test fun sharedVectorsMatchAndVerifyPythonSignatures() {
        val rows = Json.parseToJsonElement(File(System.getProperty("friday.vectors")).readText(Charsets.UTF_8)).jsonArray
        for (value in rows) {
            val row = value.jsonObject
            fun s(name: String) = row.getValue(name).jsonPrimitive.content
            val actual = Protocol.canonical(s("method"), s("path"), s("body").toByteArray(Charsets.UTF_8), s("timestamp"), s("nonce"))
            assertEquals(s("canonical"), actual.toString(Charsets.UTF_8))
            val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Protocol.publicDer(s("public_key"))))
            val verifier = Signature.getInstance("SHA256withECDSAinP1363Format")
            verifier.initVerify(key); verifier.update(actual)
            assertTrue(verifier.verify(Protocol.decode(s("signature"))))
        }
    }
    @Test fun offPausedAndForgetPreventEvenReadingTheCollector() {
        val store = MemoryStore(); var now = 10000L; val policy = Policy()
        val buffer = EventBuffer(store) { now }; val gate = CollectorGate(policy, buffer) { now }
        var reads = 0
        fun read(): JsonObject { reads++; return buildJsonObject { put("state", "on"); put("unlock_count", 0) } }
        assertNull(gate.collect("screen", ::read)); assertEquals(0, reads)
        policy.on = true; policy.pause = now + 100
        assertNull(gate.collect("screen", ::read)); assertEquals(0, reads)
        now += 101; policy.forget = true
        assertNull(gate.collect("screen", ::read)); assertEquals(0, reads)
        policy.forget = false
        assertNotNull(gate.collect("screen", ::read)); assertEquals(1, reads)
    }
    @Test fun retentionCapacityAndAcknowledgedReceipts() {
        val store = MemoryStore(); var now = 10 * 86400000L; val policy = Policy().apply { on = true }
        val buffer = EventBuffer(store) { now }
        repeat(5005) { store.put(BufferedEvent(PhoneEvent("event-$it", now / 1000.0 + it, "steps", buildJsonObject { put("count", it) }))) }
        buffer.prune(7); assertEquals(5000, store.rows().size)
        val first = buffer.pending().first(); buffer.acknowledge(setOf(first.id))
        assertEquals(1, buffer.sentLastHour().size)
        assertFalse(buffer.pending().any { it.id == first.id })
        now += 8 * 86400000L; buffer.prune(7)
        assertTrue(store.rows().isEmpty())
        buffer.add("screen", buildJsonObject { put("state", "on"); put("unlock_count", 0) }, policy)
        buffer.clear(); assertTrue(buffer.pending().isEmpty())
    }
    @Test fun senderKeepsUnreachableBatchThenAcknowledgesOnlyAcceptedIdsOverTls() {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverTls.sslSocketFactory(), false); server.start()
            val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
            val http = OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager)
                .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().url(server.url(chain.request().url.encodedPath)).build()) }.build()
            val client = SignedClient("https://mock.test.ts.net", Protocol.keyId(key.public.encoded), RequestKey { bytes ->
                Signature.getInstance("SHA256withECDSA").run { initSign(key.private); update(bytes); sign() }
            }, http)
            val store = MemoryStore(); val buffer = EventBuffer(store) { 1800000000000L }
            val event = buffer.add("screen", buildJsonObject { put("state", "on"); put("unlock_count", 0) }, Policy().apply { on = true })!!
            server.enqueue(MockResponse().setResponseCode(503))
            assertFails { BatchSender(buffer, client).send(0) }
            assertEquals(1, buffer.pending().size)
            server.enqueue(MockResponse().setBody("{\"acknowledged\":[\"${event.id}\"]}"))
            assertEquals(1, BatchSender(buffer, client).send(0)); assertTrue(buffer.pending().isEmpty())
            server.takeRequest()
            val request = server.takeRequest()
            val body = request.body.readByteArray()
            val verifier = Signature.getInstance("SHA256withECDSA").apply { initVerify(key.public); update(Protocol.canonical("POST", "/remote/v1/phone/events", body, request.getHeader("X-Timestamp")!!, request.getHeader("X-Nonce")!!)) }
            assertTrue(verifier.verify(Protocol.decode(request.getHeader("X-Signature")!!)))
        }
    }
    @Test fun qrOriginsRejectOtherServersAndCleartext() {
        listOf("http://laptop.test.ts.net", "https://evil.example", "https://foo.ts.net@evil.example", "https://foo.ts.net/path", "https://foo.ts.net?x=y").forEach { assertFails { PairingGrant.origin(it) } }
        assertEquals("https://laptop.test.ts.net", PairingGrant.origin("https://laptop.test.ts.net/"))
    }
}
