package dev.friday.companion

import android.app.Application
import android.content.Context
import androidx.room.Room
import dev.friday.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*

class RoomStore(private val db: PhoneDatabase) : BufferStore {
    override fun rows() = db.events().rows().map { BufferedEvent(PhoneEvent(it.id, it.timestamp, it.type, Json.parseToJsonElement(it.payload).jsonObject), it.sentAt) }
    override fun put(row: BufferedEvent) { db.events().put(EventRow().apply { id=row.event.id; timestamp=row.event.timestamp; type=row.event.type; payload=row.event.payload.toString(); sentAt=row.sentAt }) }
    override fun delete(ids: List<String>) { if (ids.isNotEmpty()) db.events().delete(ids) }
    override fun clear() = db.events().clear()
    override fun <T> transaction(block: () -> T): T = db.runInTransaction(java.util.concurrent.Callable { block() })
}

class CompanionApp : Application() { val repository by lazy { Repository(this) } }
val Context.repository get() = (applicationContext as CompanionApp).repository

class Repository(private val context: Context) {
    val settings = Settings(context)
    val key = DeviceKey(context)
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val database = Room.databaseBuilder(context, PhoneDatabase::class.java, "phone-buffer.db")
        .setJournalMode(androidx.room.RoomDatabase.JournalMode.TRUNCATE)
        .addCallback(object : androidx.room.RoomDatabase.Callback() {
            override fun onOpen(db: androidx.sqlite.db.SupportSQLiteDatabase) { db.execSQL("PRAGMA secure_delete=ON") }
        }).build()
    val buffer = EventBuffer(RoomStore(database), System::currentTimeMillis)
    val gate = CollectorGate(settings, buffer, System::currentTimeMillis)
    private val sync = Mutex()
    @Volatile var message = "Signals are off until you enable them."
    @Volatile var sharingRunning = false
    fun collecting(signal: String) = sharingRunning && settings.paired && settings.active(signal) &&
        (android.os.Build.VERSION.SDK_INT < 33 || context.granted(android.Manifest.permission.POST_NOTIFICATIONS))
    private var immediateAt = 0L
    fun client() = SignedClient(settings.origin, key.id, key)
    fun record(signal: String, important: Boolean = false, read: () -> JsonObject) {
        if (!collecting(signal)) return
        scope.launch {
            try {
                if (!collecting(signal)) return@launch
                val row = gate.collect(signal, read)
                if (row != null && important && System.currentTimeMillis() - immediateAt >= 30000) {
                    immediateAt = System.currentTimeMillis(); synchronize()
                }
            } catch (_: Exception) { message = "Signal unavailable; no payload was logged." }
        }
    }
    suspend fun synchronize(): Boolean = withContext(Dispatchers.IO) { sync.withLock {
        if (!settings.paired || settings.forgetting() || System.currentTimeMillis() < settings.pausedUntil()) return@withLock false
        try {
            buffer.prune(settings.retentionDays())
            val heartbeat = buildJsonObject {
                put("battery", if (collecting("battery")) SystemSignals.battery(context) ?: JsonNull else JsonNull)
                put("app_version", BuildConfig.VERSION_NAME); put("last_sync", settings.lastSync / 1000.0)
                put("signals", JsonArray(settings.enabledSignals().filter { collecting(it) }.map(::JsonPrimitive)))
            }
            val serverGeneration = client().json("POST", "phone/heartbeat", heartbeat).body.getValue("generation").jsonPrimitive.int
            if (serverGeneration != settings.generation) {
                buffer.clear(); settings.generation = serverGeneration
                message = "Laptop deletion detected; old phone backlog was cleared."
            }
            repeat(5) {
                if (settings.forgetting() || System.currentTimeMillis() < settings.pausedUntil()) return@withLock false
                if (BatchSender(buffer, client()).send(settings.generation) == 0) return@repeat
            }
            settings.lastSync = System.currentTimeMillis()
            message = "Connected; pending events are retained until acknowledged."
            true
        } catch (_: Exception) { message = "Laptop unreachable or request refused. Events stay on this phone."; false }
    } }
    suspend fun beginForget() = withContext(Dispatchers.IO) {
        settings.forgettingPending = true
        settings.enabledSignals().forEach { settings.toggle(it, false) }
        buffer.clear(); settings.lastSync = 0
        message = "Phone buffer wiped. Laptop deletion needs your approval; no signals will upload meanwhile."
        sync.withLock { buffer.clear(); settings.lastSync = 0 }
    }
    suspend fun forgetChallenge(): JsonObject = withContext(Dispatchers.IO) { sync.withLock {
        client().json("POST", "commands", buildJsonObject { put("command", "phone_forget") }).body
    } }
    suspend fun approveForget(challenge: String, pin: String) = withContext(Dispatchers.IO) { sync.withLock {
        val reply = client().json("POST", "approve", buildJsonObject {
            put("challenge", challenge); put("approval", buildJsonObject { put("pin", pin) })
        }).body
        require(reply["result"]?.jsonPrimitive?.content == "completed")
        val data = reply.getValue("data").jsonObject
        require(data["forgotten"]?.jsonPrimitive?.boolean == true)
        settings.generation = data.getValue("generation").jsonPrimitive.int
        settings.forgettingPending = false
        message = "Phone and laptop data deleted. Signals remain off."
    } }
}
