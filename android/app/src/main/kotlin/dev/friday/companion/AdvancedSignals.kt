package dev.friday.companion

import android.Manifest
import android.app.PendingIntent
import android.content.*
import android.os.Build
import com.google.android.gms.location.*
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.tasks.await
import kotlinx.serialization.json.*
import java.time.LocalDate
import java.time.ZoneId

class AdvancedSignals(private val context: Context, private val repo: Repository) {
    private fun pending(kind: String): PendingIntent = PendingIntent.getBroadcast(context, if (kind == "motion") 1 else 2,
        Intent(context, TransitionReceiver::class.java).setAction("dev.friday.$kind"), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
    suspend fun configure() {
        try {
            if (repo.collecting("motion") && context.granted(Manifest.permission.ACTIVITY_RECOGNITION)) {
                val transitions = listOf(DetectedActivity.STILL, DetectedActivity.WALKING, DetectedActivity.IN_VEHICLE).map {
                    ActivityTransition.Builder().setActivityType(it).setActivityTransition(ActivityTransition.ACTIVITY_TRANSITION_ENTER).build()
                }
                ActivityRecognition.getClient(context).requestActivityTransitionUpdates(ActivityTransitionRequest(transitions), pending("motion")).await()
            } else ActivityRecognition.getClient(context).removeActivityTransitionUpdates(pending("motion")).await()
        } catch (_: SecurityException) { repo.message = "Motion permission was revoked; no motion data collected." }
        catch (_: Exception) { repo.message = "Motion unavailable; check permission and Google Play Services." }
        try {
            val client = LocationServices.getGeofencingClient(context)
            client.removeGeofences(pending("places")).await()
            if (repo.collecting("places") && context.granted(Manifest.permission.ACCESS_FINE_LOCATION) && context.granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)) {
                val fences = repo.settings.places.map { value ->
                    val place = value.jsonObject
                    Geofence.Builder().setRequestId(place.getValue("name").jsonPrimitive.content)
                        .setCircularRegion(place.getValue("latitude").jsonPrimitive.double, place.getValue("longitude").jsonPrimitive.double, place.getValue("radius").jsonPrimitive.float)
                        .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_ENTER or Geofence.GEOFENCE_TRANSITION_EXIT)
                        .setExpirationDuration(Geofence.NEVER_EXPIRE).build()
                }
                if (fences.isNotEmpty()) client.addGeofences(GeofencingRequest.Builder().setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER).addGeofences(fences).build(), pending("places")).await()
            }
        } catch (_: SecurityException) { repo.message = "Place permission was revoked; no place data collected." }
        catch (_: Exception) { repo.message = "Places unavailable; enable background location and configure a named place." }
    }
    suspend fun health(background: Boolean) {
        if (!repo.collecting("sleep") && !repo.collecting("steps")) return
        if (HealthConnectClient.getSdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) { repo.message = "Health Connect is unavailable on this phone."; return }
        try {
            val client = HealthConnectClient.getOrCreate(context)
            val granted = client.permissionController.getGrantedPermissions()
            if (background && (client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) != HealthConnectFeatures.FEATURE_STATUS_AVAILABLE || HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND !in granted)) return
            val date = LocalDate.now(); val zone = ZoneId.systemDefault()
            val range = TimeRangeFilter.between(date.atStartOfDay(zone).toInstant(), date.plusDays(1).atStartOfDay(zone).toInstant())
            if (repo.settings.active("steps") && HealthPermission.getReadPermission(StepsRecord::class) in granted) {
                val count = client.aggregate(AggregateRequest(setOf(StepsRecord.COUNT_TOTAL), range))[StepsRecord.COUNT_TOTAL]
                if (count != null) repo.record("steps") { buildJsonObject { put("date", date.toString()); put("count", count) } }
            }
            if (repo.settings.active("sleep") && HealthPermission.getReadPermission(SleepSessionRecord::class) in granted) {
                val duration = client.aggregate(AggregateRequest(setOf(SleepSessionRecord.SLEEP_DURATION_TOTAL), range))[SleepSessionRecord.SLEEP_DURATION_TOTAL]
                if (duration != null) repo.record("sleep") { buildJsonObject { put("date", date.toString()); put("minutes", duration.toMillis() / 60000.0) } }
            }
        } catch (_: SecurityException) { repo.message = "Health permission was revoked; no aggregates collected." }
        catch (_: Exception) { repo.message = "Health aggregates unavailable; no substitute values were sent." }
    }
    fun close() {
        // No restart receiver: the user resumes foreground collection explicitly after OS termination.
        try { ActivityRecognition.getClient(context).removeActivityTransitionUpdates(pending("motion")) }
        catch (_: SecurityException) { /* Revoked access already blocks collection. */ }
        try { LocationServices.getGeofencingClient(context).removeGeofences(pending("places")) }
        catch (_: SecurityException) { /* Receiver still requires the current enabled gate. */ }
    }
}

class TransitionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val repo = context.repository
        if (repo.collecting("motion") && intent.action == "dev.friday.motion" && ActivityTransitionResult.hasResult(intent)) {
            ActivityTransitionResult.extractResult(intent)?.transitionEvents?.forEach { event ->
                val name = when (event.activityType) { DetectedActivity.STILL -> "still"; DetectedActivity.WALKING -> "walking"; DetectedActivity.IN_VEHICLE -> "in_vehicle"; else -> return@forEach }
                repo.record("motion", true) { buildJsonObject { put("activity", name) } }
            }
        }
        if (repo.collecting("places") && intent.action == "dev.friday.places") {
            val event = GeofencingEvent.fromIntent(intent) ?: return
            if (event.hasError()) return
            val transition = when (event.geofenceTransition) { Geofence.GEOFENCE_TRANSITION_ENTER -> "entered"; Geofence.GEOFENCE_TRANSITION_EXIT -> "left"; else -> return }
            val allowed = repo.settings.places.map { it.jsonObject.getValue("name").jsonPrimitive.content }.toSet()
            event.triggeringGeofences?.filter { it.requestId in allowed }?.forEach { fence ->
                repo.record("places", true) { buildJsonObject { put("place", fence.requestId); put("transition", transition) } }
            }
            // Do not read triggeringLocation: coordinates are never an event field.
        }
    }
}
