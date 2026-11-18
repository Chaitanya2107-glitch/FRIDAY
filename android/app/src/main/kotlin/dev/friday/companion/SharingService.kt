package dev.friday.companion

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import kotlinx.coroutines.*
import java.util.concurrent.TimeUnit

class SharingService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null
    private var inbox: Job? = null
    private var uploads: Job? = null
    private var controls: Job? = null
    private lateinit var collector: SystemCollector
    private lateinit var advanced: AdvancedSignals
    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel("sharing", "Phone sharing", NotificationManager.IMPORTANCE_LOW).apply { setSound(null, null); enableVibration(false) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        startForeground(41, notification())
        repository.sharingRunning = true
        collector = SystemCollector(this, repository); collector.start()
        advanced = AdvancedSignals(this, repository)
    }
    private fun notification(): Notification {
        val active = repository.settings.enabledSignals().filter { repository.settings.active(it) }
        val names = active.joinToString(", ") { if (it == "app_usage") "app" else it.replace('_', ' ') }.ifBlank { if (System.currentTimeMillis() < repository.settings.pausedUntil()) "paused" else "none" }
        val intent = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, "sharing").setSmallIcon(R.drawable.ic_friday).setContentTitle("FRIDAY connected — sharing: $names")
            .setContentText(repository.message).setContentIntent(intent).setOngoing(true).setSilent(true).build()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "dev.friday.STOP_ALARM") Alarm.stop(this)
        repository.presence.tick()
        if (controls?.isActive != true) controls = scope.launch {
            while (isActive) { repository.presence.tick(); delay(1000) }
        }
        if (inbox?.isActive != true) inbox = scope.launch { repository.handoff.inbox() }
        if (uploads?.isActive != true) uploads = scope.launch {
            while (isActive) {
                if (!repository.settings.forgetting() && System.currentTimeMillis() >= repository.settings.pausedUntil()) {
                    runCatching { Transfers(this@SharingService, repository).upload() }
                }
                delay(10000)
            }
        }
        loop?.cancel()
        loop = scope.launch {
            var previousConfiguration = ""
            var syncAt = 0L; var healthAt = 0L
            while (isActive) {
                if (android.os.Build.VERSION.SDK_INT >= 33 && !this@SharingService.granted(android.Manifest.permission.POST_NOTIFICATIONS)) {
                    repository.sharingRunning = false
                    repository.message = "Sharing stopped: restore notification permission, then tap Resume."
                    stopSelf(); break
                }
                val configuration = repository.settings.enabledSignals().filter { repository.collecting(it) }.sorted().joinToString() + repository.settings.places.toString()
                if (configuration != previousConfiguration) { advanced.configure(); previousConfiguration = configuration }
                runCatching { collector.tick() }.onFailure { repository.message = "A signal permission is unavailable; check Sharing controls." }
                val now = System.currentTimeMillis()
                if (now - healthAt >= 300000) { advanced.health(background = true); healthAt = now }
                if (now - syncAt >= 300000) { repository.synchronize(); syncAt = now }
                getSystemService(NotificationManager::class.java).notify(41, notification())
                delay(15000)
            }
        }
        return START_NOT_STICKY  // A visible user action restarts collection after OS termination.
    }
    override fun onTimeout(startId: Int, fgsType: Int) { stopSelf() }
    override fun onDestroy() { repository.sharingRunning = false; repository.presence.disconnect(); Alarm.stop(this); controls?.cancel(); inbox?.cancel(); uploads?.cancel(); loop?.cancel(); collector.close(); advanced.close(); scope.cancel(); super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null
    companion object {
        fun scheduleSync(context: Context) {
            val work = OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniqueWork("phone-actions", ExistingWorkPolicy.APPEND_OR_REPLACE, work)
        }
        fun start(context: Context) {
            if (!context.repository.settings.paired || (!context.repository.settings.connection && context.repository.settings.enabledSignals().isEmpty())) return
            ContextCompat.startForegroundService(context, Intent(context, SharingService::class.java))
            val work = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("phone-sync", ExistingPeriodicWorkPolicy.KEEP, work)
        }
    }
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val repo = applicationContext.repository
        if (repo.settings.forgetting()) return@withContext Result.success()
        if (repo.commands.rows().none { it.state == "waiting" } && Transfers(applicationContext, repo).waiting().isEmpty() && repo.buffer.pending().isEmpty()) return@withContext Result.success()
        if (!repo.synchronize()) return@withContext Result.retry()
        if (!repo.settings.forgetting() && System.currentTimeMillis() >= repo.settings.pausedUntil()) Transfers(applicationContext, repo).upload(2)
        if (Transfers(applicationContext, repo).waiting().isEmpty()) Result.success() else Result.retry()
    }
}
