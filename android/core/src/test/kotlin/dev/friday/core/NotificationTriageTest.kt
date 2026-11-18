package dev.friday.core

import kotlin.test.*
import kotlinx.serialization.json.*
import org.junit.Test

class NotificationTriageTest {
    private val now = 1800000000000L
    private val shopping = NotificationMetadata("a".repeat(64), "com.shop.app", "promo", 2)
    private fun policy(situation: String = "study") = TriagePolicy(situation, now / 1000.0 + 60,
        emptySet(), emptySet(), true, setOf(shopping.app))
    @Test fun snoozeIsOffUnlessEveryLocalAndRemoteGateAllowsIt() {
        val rule = SnoozePolicy { now }
        assertNull(rule.duration(shopping, policy(), false, true, true))
        assertNull(rule.duration(shopping, policy(), true, false, true))
        assertNull(rule.duration(shopping, policy(), true, true, false))
        assertNull(rule.duration(shopping, policy().copy(snooze = false), true, true, true))
        assertNull(rule.duration(shopping, policy().copy(blocked = emptySet()), true, true, true))
        assertNull(rule.duration(shopping, policy("free"), true, true, true))
        assertEquals(10000L, rule.duration(shopping, policy(), true, true, true))
    }
    @Test fun vipUrgentCallsAlarmsAndOngoingNotificationsAlwaysPass() {
        val rule = SnoozePolicy { now }
        for (meta in listOf(shopping.copy(category = "call"), shopping.copy(category = "alarm"),
            shopping.copy(ongoing = true), shopping.copy(importance = 4))) {
            assertNull(rule.duration(meta, policy(), true, true, true))
        }
        assertNull(rule.duration(shopping, policy().copy(vip = setOf(shopping.app)), true, true, true))
        assertNull(rule.duration(shopping, policy().copy(urgent = setOf(shopping.app)), true, true, true))
        assertNull(rule.duration(shopping, policy(), true, true, true, localVip = setOf(shopping.app)))
        assertNull(rule.duration(shopping, policy(), true, true, true, localUrgent = setOf(shopping.app)))
    }
    @Test fun snoozesExpireAtContextExitWithoutAHiddenUnsnoozeApi() {
        var clock = now
        val rule = SnoozePolicy { clock }
        val lease = rule.duration(shopping, policy(), true, true, true)!!
        assertEquals(SnoozePolicy.LEASE_MS, lease)
        assertNull(rule.duration(shopping, policy("free"), true, true, true))
        clock += lease
        assertTrue(clock >= now + lease) // Android restores the bounded timed snooze itself.
        assertNull(rule.duration(shopping, policy().copy(until = clock / 1000.0), true, true, true))
    }
    @Test fun userActionsTrainWhileSystemRemovalsAndOurSnoozesRemainNeutral() {
        assertEquals("opened", NotificationSignals.outcome(1))
        assertEquals("dismissed", NotificationSignals.outcome(2)); assertEquals("dismissed", NotificationSignals.outcome(3))
        for (reason in listOf(4, 8, 9, 12, 18, 19, 23)) assertEquals("removed", NotificationSignals.outcome(reason))
        val identity = NotificationSignals.identity("salt", "account-sensitive-key", 123)
        assertTrue(identity.matches(Regex("[a-f0-9]{64}")))
        assertNotEquals(identity, NotificationSignals.identity("other-salt", "account-sensitive-key", 123))
    }
    @Test fun modeRestorationPreservesManualChangesAndRequiresOwnToken() {
        val lease = ModeLease("token", "ringer", 2, 0, now / 1000.0 + 60)
        assertFalse(lease.shouldRestore(now / 1000.0, 0))
        assertTrue(lease.shouldRestore(now / 1000.0, 0, true))
        assertFalse(lease.shouldRestore(now / 1000.0 + 61, 1))
        assertTrue(lease.shouldRestore(now / 1000.0 + 61, 0))
        val coupled = lease.copy(previousDnd = 1, appliedDnd = 2)
        assertTrue(coupled.preservesDnd(2))
        assertFalse(coupled.preservesDnd(3)) // Changing ringer must not undo a later manual DND choice.
    }
    @Test fun controlPoliciesRejectUnknownFieldsAndStaleOrOversizedLeases() {
        fun body(until: Double) = buildJsonObject {
            put("situation", "study"); put("until", until); put("snooze", true)
            put("vip", JsonArray(emptyList())); put("urgent", JsonArray(emptyList()))
        }
        assertFails { TriagePolicy.parse(body(now / 1000.0), now / 1000.0) }
        assertFails { TriagePolicy.parse(body(now / 1000.0 + 121), now / 1000.0) }
        assertFalse(TriagePolicy.parse(body(now / 1000.0 + 60), now / 1000.0).blocked.isNotEmpty())
        assertFails { TriagePolicy.packageName("../bad") }
        assertFails { ModeRequest.parse(buildJsonObject {
            put("mode", "unlock"); put("value", 0); put("token", "a".repeat(32)); put("until", now / 1000.0 + 10)
        }, now / 1000.0) }
    }
}
