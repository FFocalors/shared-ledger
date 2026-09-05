package com.ffocalors.sharedledger.ui.activity

import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.data.activity.ActivityMember
import com.ffocalors.sharedledger.data.activity.ActivityPermissions
import com.ffocalors.sharedledger.data.activity.ActivityRole
import com.ffocalors.sharedledger.data.activity.ActivitySummary
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.activity.ActivityRepository
import com.ffocalors.sharedledger.data.activity.ActivityFinancialStatus
import com.ffocalors.sharedledger.data.activity.LedgerUnit
import com.ffocalors.sharedledger.data.activity.Participant
import com.ffocalors.sharedledger.ui.screens.JoinActivityStatus
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun homeMappingUsesRealIdsAndActivityType() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply { activities = listOf(summary) }
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadHome()
        advanceUntilIdle()

        assertEquals("activity-1", viewModel.home.value.activities.single().activityId)
        assertEquals(com.ffocalors.sharedledger.ui.components.ActivityKind.Large, viewModel.home.value.activities.single().kind)
    }

    @Test
    fun duplicateCreateIsIgnoredWhileRequestIsInFlight() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val gate = CompletableDeferred<Result<ActivitySummary>>()
        val repository = FakeActivityRepository(summary).apply { createGate = gate }
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.createActivity("旅行", com.ffocalors.sharedledger.ui.components.ActivityKind.Large, false) {}
        viewModel.createActivity("旅行", com.ffocalors.sharedledger.ui.components.ActivityKind.Large, false) {}
        advanceUntilIdle()
        assertEquals(1, repository.createCalls.get())
        gate.complete(Result.success(summary))
        advanceUntilIdle()
        assertEquals("活动已创建", viewModel.message.value)
    }

    @Test
    fun forceRefreshReplacesPreviousUserHomeState() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val first = summary.copy(id = "activity-user-a", name = "A 的活动")
        val second = summary.copy(id = "activity-user-b", name = "B 的活动")
        val repositoryA = FakeActivityRepository(first).apply { activities = listOf(first) }
        val repositoryB = FakeActivityRepository(second).apply { activities = listOf(second) }
        val viewModelA = ActivityViewModel(repositoryA, "user-a")
        val viewModelB = ActivityViewModel(repositoryB, "user-b")

        viewModelA.loadHome()
        viewModelB.loadHome()
        advanceUntilIdle()

        assertEquals("activity-user-a", viewModelA.home.value.activities.single().activityId)
        assertEquals("activity-user-b", viewModelB.home.value.activities.single().activityId)

        repositoryB.activities = emptyList()
        viewModelB.refreshHome()
        advanceUntilIdle()
        assertTrue(viewModelB.home.value.activities.isEmpty())
        assertEquals("activity-user-a", viewModelA.home.value.activities.single().activityId)
    }

    @Test
    fun joinCanCompleteWithoutClaimingParticipant() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply {
            joinDetail = ActivityDetail(
                summary = summary,
                members = emptyList(),
                participants = emptyList(),
                ledgerUnits = emptyList(),
                currentUserRole = ActivityRole.Member,
                permissions = ActivityPermissions.forRole(ActivityRole.Member),
            )
        }
        val viewModel = ActivityViewModel(repository, "user-2")

        viewModel.joinActivity("12345678")
        advanceUntilIdle()
        assertEquals(JoinActivityStatus.ReadyToJoin, viewModel.join.value.status)
        assertTrue(viewModel.join.value.preview.participants.isEmpty())

        viewModel.completeJoinWithoutClaim()
        advanceUntilIdle()

        assertEquals(JoinActivityStatus.Joined, viewModel.join.value.status)
    }

    @Test
    fun creatorCanBindAnUnclaimedParticipantFromManagement() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()
        assertTrue(viewModel.managementState("activity-1")?.canBindParticipant == true)
        assertEquals("Alex", viewModel.managementState("activity-1")?.members?.single()?.name)
        assertEquals("未绑定参与人", viewModel.managementState("activity-1")?.members?.single()?.detail)

        viewModel.bindCurrentUser("activity-1", "p")
        advanceUntilIdle()

        assertEquals(1, repository.claimCalls.get())
        assertEquals("p", viewModel.managementState("activity-1")?.currentUserParticipantId)
        assertEquals("Alex", viewModel.managementState("activity-1")?.participants?.single()?.boundUserName)
        assertTrue(viewModel.isCurrentUserBound(viewModel.detail("activity-1").value.detail))
    }

    @Test
    fun unboundUserCanBindAfterJoiningWithoutClaim() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val joinedDetail = ActivityDetail(
            summary = summary,
            members = listOf(ActivityMember("m-2", "user-2", "成员B", false)),
            participants = listOf(Participant("p-2", "activity-1", "成员B", 0)),
            ledgerUnits = emptyList(),
            currentUserRole = ActivityRole.Member,
            permissions = ActivityPermissions.forRole(ActivityRole.Member),
        )
        val repository = FakeActivityRepository(summary).apply {
            joinDetail = joinedDetail
            memberUserId = "user-2"
            memberDisplayName = "成员B"
            memberIsCreator = false
            memberParticipantId = "p-2"
        }
        val viewModel = ActivityViewModel(repository, "user-2")

        viewModel.joinActivity("12345678")
        advanceUntilIdle()
        viewModel.completeJoinWithoutClaim()
        advanceUntilIdle()
        viewModel.loadDetail("activity-1", force = true)
        advanceUntilIdle()
        assertTrue(viewModel.managementState("activity-1")?.canBindParticipant == true)

        viewModel.bindCurrentUser("activity-1", "p-2")
        advanceUntilIdle()

        assertEquals("p-2", repository.lastClaimedParticipantId)
    }

    @Test
    fun unboundUserDoesNotPassParticipantBusinessGate() {
        val detail = ActivityDetail(
            summary = summary,
            members = listOf(ActivityMember("m-2", "user-2", "成员B", false)),
            participants = listOf(Participant("p-2", "activity-1", "成员B", 0)),
            ledgerUnits = emptyList(),
            currentUserRole = ActivityRole.Member,
            permissions = ActivityPermissions.forRole(ActivityRole.Member),
        )

        assertTrue(!ActivityViewModel(FakeActivityRepository(summary), "user-2").isCurrentUserBound(detail))
    }

    private val summary = ActivitySummary(
        id = "activity-1", name = "日本旅行", type = ActivityType.Large, joinCode = "12345678",
        baseCurrency = "CNY", multiCurrencyEnabled = false, createdBy = "user-1", archivedAt = null,
        participantCount = 1, participantNames = listOf("Alex"), status = ActivityFinancialStatus.Active,
        totalDebt = "0.0", totalPrepayment = "0.0",
    )

    private class FakeActivityRepository(
        private val defaultSummary: ActivitySummary,
    ) : ActivityRepository {
        var activities: List<ActivitySummary> = emptyList()
        var createGate: CompletableDeferred<Result<ActivitySummary>>? = null
        var joinDetail: ActivityDetail? = null
        val createCalls = AtomicInteger()
        val claimCalls = AtomicInteger()
        var lastClaimedParticipantId: String? = null
        var memberUserId: String = "user-1"
        var memberDisplayName: String = "Alex"
        var memberIsCreator: Boolean = true
        var memberParticipantId: String = "p"
        override suspend fun listActivities() = Result.success(activities)
        override suspend fun getActivity(activityId: String) = Result.success(
            ActivityDetail(
                defaultSummary,
                listOf(ActivityMember("m", memberUserId, memberDisplayName, memberIsCreator, lastClaimedParticipantId)),
                listOf(Participant(memberParticipantId, activityId, "Alex", 0, lastClaimedParticipantId, lastClaimedParticipantId?.let { "Alex" })),
                listOf(LedgerUnit("u", activityId, "日本旅行", "root")),
                ActivityRole.Creator,
                ActivityPermissions.forRole(ActivityRole.Creator),
            ),
        )
        override suspend fun createActivity(name: String, type: ActivityType, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<ActivitySummary> {
            createCalls.incrementAndGet()
            return createGate?.await() ?: Result.success(defaultSummary)
        }
        override suspend fun joinActivity(joinCode: String) = Result.success(joinDetail ?: getActivity("activity-1").getOrThrow())
        override suspend fun createParticipant(activityId: String, name: String) = Result.success(Participant("p", activityId, name, 0))
        override suspend fun claimParticipant(activityId: String, participantId: String): Result<Unit> {
            claimCalls.incrementAndGet()
            lastClaimedParticipantId = participantId
            return Result.success(Unit)
        }
        override suspend fun unclaimParticipant(activityId: String) = Result.success(Unit)
        override suspend fun deleteParticipant(participantId: String) = Result.success(Unit)
        override suspend fun createSubActivity(activityId: String, name: String) = Result.success(LedgerUnit("u2", activityId, name, "sub_activity"))
        override suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean) = Result.success(Unit)
        override suspend fun archiveActivity(activityId: String) = Result.success(Unit)
        override suspend fun unarchiveActivity(activityId: String) = Result.success(Unit)
        override suspend fun deleteActivity(activityId: String) = Result.success(Unit)
        override suspend fun removeMember(activityId: String, userId: String) = Result.success(Unit)
        override suspend fun transferCreator(activityId: String, newCreatorUserId: String) = Result.success(Unit)
    }
}
