package dev.friday.core

import java.io.IOException
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlin.test.*
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Test

class MemoryCommands : CommandStore {
    private val values = linkedMapOf<String, WaitingCommand>()
    override fun rows() = values.values.toList()
    override fun put(row: WaitingCommand) { values[row.id] = row }
    override fun remove(id: String) { values.remove(id) }
}

class CommandQueueTest {
    @Test fun cancellationAndReadingStayResponsiveDuringNetworkSend() {
        val queue = CommandQueue(MemoryCommands()) { 1800000000000 }
        val first = queue.add("ring_laptop", buildJsonObject {})
        val second = queue.add("start_focus", buildJsonObject {})
        val entered = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        val workers = java.util.concurrent.Executors.newFixedThreadPool(2)
        val sent = java.util.concurrent.atomic.AtomicInteger()
        try {
            val sending = workers.submit<Int> { queue.drain {
                sent.incrementAndGet(); entered.countDown()
                check(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                buildJsonObject { put("result", "completed") }
            } }
            assertTrue(entered.await(2, java.util.concurrent.TimeUnit.SECONDS))
            workers.submit {
                assertEquals(2, queue.rows().size)
                queue.dismiss(first.id); queue.dismiss(second.id)
            }.get(1, java.util.concurrent.TimeUnit.SECONDS)
            assertEquals(0, queue.drain { error("Concurrent drain must not send") })
            release.countDown()
            assertEquals(1, sending.get(2, java.util.concurrent.TimeUnit.SECONDS))
            assertEquals(1, sent.get()); assertTrue(queue.rows().isEmpty())
        } finally { release.countDown(); workers.shutdownNow() }
    }
    @Test fun expiryDuringSendPreventsNextCommandAndLateReceiptRestoration() {
        val now = java.util.concurrent.atomic.AtomicLong(1800000000000)
        val queue = CommandQueue(MemoryCommands(), now::get)
        queue.add("ring_laptop", buildJsonObject {}, 1)
        queue.add("start_focus", buildJsonObject {}, 1)
        var sent = 0
        assertEquals(1, queue.drain {
            sent++; now.addAndGet(2000)
            buildJsonObject { put("result", "completed") }
        })
        assertEquals(1, sent)
        assertTrue(queue.rows().all { it.state == "expired" })
    }
    @Test fun equalTimestampKeepsEnqueueOrderAndRiskChangeIsRefused() {
        val queue = CommandQueue(MemoryCommands()) { 1800000000000 }
        val first = queue.add("start_focus", buildJsonObject {})
        val second = queue.add("stop_focus", buildJsonObject {})
        val ids = mutableListOf<String>()
        queue.drain { ids += it.getValue("id").jsonPrimitive.content; buildJsonObject { put("result", "approval_required") } }
        assertEquals(listOf(first.id, second.id), ids)
        assertTrue(queue.rows().all { it.state == "refused" })
        assertEquals(0, queue.drain { error("Changed risk must never retry") })
    }
    @Test fun confirmBlockedAndUnknownCommandsNeverQueue() {
        val store = MemoryCommands(); val queue = CommandQueue(store) { 1800000000000 }
        listOf("lock_pc", "sleep_pc", "send_message", "delete_note", "clear_notes", "phone_forget", "open_app", "exec", "change_settings", "unknown").forEach {
            assertFailsWith<IllegalArgumentException> { queue.add(it, buildJsonObject {}) }
        }
        assertTrue(store.rows().isEmpty())
        assertFails { queue.add("ring_laptop", buildJsonObject {}, 86401) }
        assertFails { queue.add("ring_laptop", buildJsonObject {}, 0) }
    }
    @Test fun expiryOrderingReceiptsAndNoRetryOfUncertain() {
        var now = 1800000000000L
        val store = MemoryCommands(); val queue = CommandQueue(store) { now }
        val expired = queue.add("ring_laptop", buildJsonObject {}, 1)
        now += 2000
        val first = queue.add("start_focus", buildJsonObject { put("minutes", 25) })
        now += 1000
        val second = queue.add("stop_focus", buildJsonObject {})
        val sent = mutableListOf<String>()
        assertEquals(2, queue.drain {
            sent += it.getValue("id").jsonPrimitive.content
            buildJsonObject { put("result", if (sent.size == 1) "uncertain" else "completed") }
        })
        assertEquals(listOf(first.id, second.id), sent)
        assertEquals("expired", queue.rows().first { it.id == expired.id }.state)
        assertEquals(0, queue.drain { error("Receipts must not run twice") })
    }
    @Test fun offlineAndRefusedHaveDifferentOutcomes() {
        val store = MemoryCommands(); val queue = CommandQueue(store) { 1800000000000 }
        val first = queue.add("ring_laptop", buildJsonObject {})
        val second = queue.add("start_focus", buildJsonObject {})
        assertEquals(0, queue.drain { throw IOException("offline") })
        assertTrue(queue.rows().all { it.state == "waiting" })
        assertEquals(2, queue.drain { if (it.getValue("id").jsonPrimitive.content == first.id) throw RequestRefused(404) else buildJsonObject { put("result", "completed") } })
        assertEquals("refused", queue.rows().first { it.id == first.id }.state)
        assertEquals("completed", queue.rows().first { it.id == second.id }.state)
    }
    @Test fun retryUsesSameIdAndSignedBytesAgainstTlsFakeServer() {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverTls.sslSocketFactory(), false); server.start()
            val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
            val http = OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager)
                .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().url(server.url(chain.request().url.encodedPath)).build()) }.build()
            val client = SignedClient("https://mock.test.ts.net", Protocol.keyId(pair.public.encoded), RequestKey { bytes ->
                Signature.getInstance("SHA256withECDSA").run { initSign(pair.private); update(bytes); sign() }
            }, http)
            val queue = CommandQueue(MemoryCommands()) { 1800000000000 }
            val row = queue.add("ring_laptop", buildJsonObject {})
            server.enqueue(MockResponse().setResponseCode(503))
            assertEquals(0, queue.drain { client.json("POST", "queue", it).body })
            server.enqueue(MockResponse().setBody("{\"result\":\"completed\"}"))
            assertEquals(1, queue.drain { request ->
                try { client.json("POST", "queue", request).body } catch (failure: Exception) { throw AssertionError("TLS retry failed", failure) }
            })
            val first = server.takeRequest(); val second = server.takeRequest()
            assertEquals(first.body.clone().readUtf8(), second.body.clone().readUtf8())
            assertEquals(row.id, Json.parseToJsonElement(second.body.clone().readUtf8()).jsonObject.getValue("id").jsonPrimitive.content)
            val verifier = Signature.getInstance("SHA256withECDSA").apply {
                initVerify(pair.public); update(Protocol.canonical("POST", "/remote/v1/queue", second.body.readByteArray(), second.getHeader("X-Timestamp")!!, second.getHeader("X-Nonce")!!))
            }
            assertTrue(verifier.verify(Protocol.decode(second.getHeader("X-Signature")!!)))
            assertNotEquals(first.getHeader("X-Nonce"), second.getHeader("X-Nonce"))
        }
    }
    @Test fun fileNamesAndLinksRejectExecutionAndPaths() {
        listOf("../notes.txt", "/tmp/file.txt", "C:\\file.txt", "notes.exe", "notes.ps1.txt", "a.JS", "x.apk", "x.sh", "a\u0000.txt", "a.").forEach { assertFails { TransferRules.name(it) } }
        assertEquals("lecture notes.pdf", TransferRules.name("lecture notes.pdf"))
        listOf("javascript:alert(1)", "file:///etc/passwd", "intent://app", "https://user:pass@example.com", "not a link").forEach { assertNull(TransferRules.link(it)) }
        assertEquals("https://example.com/notes", TransferRules.link("https://example.com/notes"))
    }
}
