package com.ffocalors.sharedledger.ui.activity

import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.data.activity.ActivityMember
import com.ffocalors.sharedledger.data.activity.ActivityPermissions
import com.ffocalors.sharedledger.data.activity.ActivityFailureKind
import com.ffocalors.sharedledger.data.activity.ActivityOperationException
import com.ffocalors.sharedledger.data.activity.ActivityRole
import com.ffocalors.sharedledger.data.activity.ActivitySummary
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.activity.ActivityRepository
import com.ffocalors.sharedledger.data.activity.ActivityFinancialStatus
import com.ffocalors.sharedledger.data.activity.LedgerUnit
import com.ffocalors.sharedledger.data.activity.Participant
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepository
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareSnapshot
import com.ffocalors.sharedledger.ui.screens.JoinActivityStatus
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ActivityViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun homeMappingUsesRealIdsAndActivityType() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply { activities = listOf(summary) }
        val viewModel = ActivityViewModel(repository, "user-1", FakeParticipantExpenseShareRepository())

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
        val viewModelA = ActivityViewModel(repositoryA, "user-a", FakeParticipantExpenseShareRepository())
        val viewModelB = ActivityViewModel(repositoryB, "user-b", FakeParticipantExpenseShareRepository())

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
    fun homeShareFailureIsRetryableErrorAndUnboundRemainsDistinct() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply { activities = listOf(summary) }
        val failingViewModel = ActivityViewModel(
            repository,
            "user-1",
            FakeParticipantExpenseShareRepository(Result.failure(IllegalStateException("network"))),
        )

        failingViewModel.loadHome()
        advanceUntilIdle()

        assertEquals("我的应承担金额加载失败，请重试", failingViewModel.home.value.errorMessage)
        assertTrue(failingViewModel.home.value.activities.isEmpty())

        val unboundViewModel = ActivityViewModel(
            repository,
            "user-1",
            FakeParticipantExpenseShareRepository(Result.success(ParticipantExpenseShareSnapshot.unbound())),
        )
        unboundViewModel.loadHome()
        advanceUntilIdle()

        assertTrue(unboundViewModel.home.value.errorMessage == null)
        assertTrue(!unboundViewModel.home.value.activities.single().amountAvailable)
        assertTrue(unboundViewModel.home.value.activities.single().totalAmount == null)
    }

    @Test
    fun forceRefreshReloadsFinancialStatusAfterReturningFromChild() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val zero = summary.copy(totalDebt = "0.0")
        val updated = summary.copy(totalDebt = "150.0")
        val repository = FakeActivityRepository(zero).apply {
            detailOverride = { if (detailCalls.get() == 1) detailFor(zero) else detailFor(updated) }
        }
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()
        assertEquals("0.0", viewModel.detail("activity-1").value.detail?.summary?.totalDebt)

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()
        assertEquals(1, repository.detailCalls.get())

        viewModel.loadDetail("activity-1", force = true)
        advanceUntilIdle()
        assertEquals("150.0", viewModel.detail("activity-1").value.detail?.summary?.totalDebt)
        assertEquals(2, repository.detailCalls.get())
    }

    @Test
    fun forceRefreshClearsRemovedActivityDetailButNetworkFailureKeepsCachedDetail() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()
        assertTrue(viewModel.detail("activity-1").value.detail != null)

        repository.detailResult = Result.failure(
            ActivityOperationException(
                "你没有权限执行此操作，或已不是活动成员",
                kind = ActivityFailureKind.PermissionDenied,
            ),
        )
        viewModel.loadDetail("activity-1", force = true)
        advanceUntilIdle()
        assertEquals(null, viewModel.detail("activity-1").value.detail)

        repository.detailResult = Result.success(repository.detailFor(summary))
        viewModel.loadDetail("activity-1", force = true)
        advanceUntilIdle()
        repository.detailResult = Result.failure(
            ActivityOperationException(
                "网络连接失败，请检查网络后重试",
                kind = ActivityFailureKind.Network,
            ),
        )
        viewModel.loadDetail("activity-1", force = true)
        advanceUntilIdle()
        assertTrue(viewModel.detail("activity-1").value.detail != null)
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
    fun settingsToggleKeepsTheLoadedActivityBaseCurrency() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val jpySummary = summary.copy(baseCurrency = "JPY")
        val repository = FakeActivityRepository(jpySummary)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()
        viewModel.updateSettings("activity-1", "日本旅行", multiCurrency = true)
        advanceUntilIdle()

        assertEquals("JPY", repository.lastUpdatedBaseCurrency)
    }

    @Test
    fun managementStateExposesParticipantLockAndStructuredDebtState() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val locked = summary.copy(
            totalDebt = "0.00",
            participantsLockedAt = "2026-09-07T10:00:00Z",
        )
        val repository = FakeActivityRepository(locked)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()

        val state = viewModel.managementState("activity-1")
        assertTrue(state?.participantListLocked == true)
        assertTrue(state?.participantListLockMessage?.contains("不能新增或删除") == true)
        assertTrue(state?.hasOutstandingDebt == false)

        viewModel.deleteParticipant("p", "activity-1")
        advanceUntilIdle()
        assertEquals(0, repository.deleteParticipantCalls.get())
        assertEquals("参与人名单已锁定，不能删除参与人", viewModel.message.value)
        viewModel.clearMessage()
        assertNull(viewModel.message.value)
    }

    @Test
    fun archivedManagementStateIsReadOnlyButExposesCreatorUnarchiveAction() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val archived = summary.copy(archivedAt = "2026-09-07T10:00:00Z")
        val repository = FakeActivityRepository(archived)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.loadDetail("activity-1")
        advanceUntilIdle()

        val state = viewModel.managementState("activity-1")
        assertEquals(com.ffocalors.sharedledger.ui.screens.ActivityManagementStatus.Archived, state?.status)
        assertTrue(state?.showSettings == false)
        assertTrue(state?.canManageParticipants == false)
        assertTrue(state?.canManageMembers == false)
        assertTrue(state?.canBindParticipant == false)
        assertTrue(state?.canUnbindParticipant == false)
        assertTrue(state?.showTransferOwnershipAction == false)
        assertTrue(state?.showDeleteAction == false)
        assertTrue(state?.canArchiveActivity == false)
        assertTrue(state?.canUnarchiveActivity == true)

        viewModel.createSubActivity("activity-1", "不应创建")
        advanceUntilIdle()
        assertEquals(0, repository.createSubActivityCalls.get())

        viewModel.unarchiveActivity("activity-1")
        advanceUntilIdle()
        assertEquals(1, repository.unarchiveCalls.get())
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

    @Test
    fun personalOverviewDetailFailureIsVisibleAndRetryCanLoadRealCounts() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply {
            activities = listOf(summary)
            lastClaimedParticipantId = "p"
            detailResult = Result.failure(
                ActivityOperationException(
                    "网络连接失败，请检查网络后重试",
                    kind = ActivityFailureKind.Network,
                ),
            )
        }
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.refreshPersonalOverview()
        advanceUntilIdle()

        assertNull(viewModel.personalOverview.value.overview)
        assertTrue(viewModel.personalOverview.value.errorMessage?.contains("日本旅行") == true)
        assertTrue(!viewModel.personalOverview.value.isLoading)

        repository.detailResult = Result.success(repository.detailFor(summary))
        viewModel.refreshPersonalOverview()
        advanceUntilIdle()

        assertEquals(1, viewModel.personalOverview.value.overview?.initiatedCount)
        assertEquals(1, viewModel.personalOverview.value.overview?.claimedIdentityCount)
        assertNull(viewModel.personalOverview.value.errorMessage)
    }

    @Test
    fun personalOverviewRefreshKeepsCachedRealDataAndShowsRefreshFailure() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary).apply { activities = listOf(summary) }
        val viewModel = ActivityViewModel(repository, "user-1")
        viewModel.refreshPersonalOverview()
        advanceUntilIdle()
        val cachedOverview = viewModel.personalOverview.value.overview

        val refreshGate = CompletableDeferred<Result<List<ActivitySummary>>>()
        repository.listGate = refreshGate
        viewModel.refreshPersonalOverview()
        runCurrent()

        assertTrue(viewModel.personalOverview.value.isRefreshing)
        assertEquals(cachedOverview, viewModel.personalOverview.value.overview)

        refreshGate.complete(Result.failure(ActivityOperationException("网络连接失败，请检查网络后重试")))
        advanceUntilIdle()

        assertTrue(!viewModel.personalOverview.value.isRefreshing)
        assertEquals(cachedOverview, viewModel.personalOverview.value.overview)
        assertEquals("网络连接失败，请检查网络后重试", viewModel.personalOverview.value.errorMessage)
    }

    @Test
    fun personalOverviewRefreshReloadsActivitiesChangedSincePreviousEntry() = runTest(dispatcher) {
        Dispatchers.setMain(dispatcher)
        val repository = FakeActivityRepository(summary)
        val viewModel = ActivityViewModel(repository, "user-1")

        viewModel.refreshPersonalOverview()
        advanceUntilIdle()
        assertEquals(0, viewModel.personalOverview.value.overview?.initiatedCount)

        repository.activities = listOf(summary)
        viewModel.refreshPersonalOverview()
        advanceUntilIdle()

        assertEquals(1, viewModel.personalOverview.value.overview?.initiatedCount)
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
        var listGate: CompletableDeferred<Result<List<ActivitySummary>>>? = null
        var createGate: CompletableDeferred<Result<ActivitySummary>>? = null
        var joinDetail: ActivityDetail? = null
        val createCalls = AtomicInteger()
        val claimCalls = AtomicInteger()
        val createSubActivityCalls = AtomicInteger()
        val unarchiveCalls = AtomicInteger()
        val detailCalls = AtomicInteger()
        var detailOverride: (() -> ActivityDetail)? = null
        var detailResult: Result<ActivityDetail>? = null
        var lastClaimedParticipantId: String? = null
        var memberUserId: String = "user-1"
        var memberDisplayName: String = "Alex"
        var memberIsCreator: Boolean = true
        var memberParticipantId: String = "p"
        var lastUpdatedBaseCurrency: String? = null
        val deleteParticipantCalls = AtomicInteger()
        override suspend fun listActivities() = listGate?.await() ?: Result.success(activities)
        override suspend fun getActivity(activityId: String): Result<ActivityDetail> {
            detailCalls.incrementAndGet()
            return detailResult ?: Result.success(detailOverride?.invoke() ?: detailFor(defaultSummary, activityId))
        }

        fun detailFor(summary: ActivitySummary, activityId: String = summary.id) = ActivityDetail(
            summary,
            listOf(ActivityMember("m", memberUserId, memberDisplayName, memberIsCreator, lastClaimedParticipantId)),
            listOf(Participant(memberParticipantId, activityId, "Alex", 0, lastClaimedParticipantId, lastClaimedParticipantId?.let { "Alex" })),
            listOf(LedgerUnit("u", activityId, "日本旅行", "root")),
            ActivityRole.Creator,
            ActivityPermissions.forRole(ActivityRole.Creator),
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
        override suspend fun deleteParticipant(participantId: String): Result<Unit> {
            deleteParticipantCalls.incrementAndGet()
            return Result.success(Unit)
        }
        override suspend fun createSubActivity(activityId: String, name: String): Result<LedgerUnit> {
            createSubActivityCalls.incrementAndGet()
            return Result.success(LedgerUnit("u2", activityId, name, "sub_activity"))
        }
        override suspend fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrencyEnabled: Boolean): Result<Unit> {
            lastUpdatedBaseCurrency = baseCurrency
            return Result.success(Unit)
        }
        override suspend fun archiveActivity(activityId: String) = Result.success(Unit)
        override suspend fun unarchiveActivity(activityId: String): Result<Unit> {
            unarchiveCalls.incrementAndGet()
            return Result.success(Unit)
        }
        override suspend fun deleteActivity(activityId: String) = Result.success(Unit)
        override suspend fun removeMember(activityId: String, userId: String) = Result.success(Unit)
        override suspend fun transferCreator(activityId: String, newCreatorUserId: String) = Result.success(Unit)
    }
}

private class FakeParticipantExpenseShareRepository(
    private val result: Result<ParticipantExpenseShareSnapshot> = Result.success(
        ParticipantExpenseShareSnapshot(
            isBound = true,
            activityTotalBaseAmount = java.math.BigDecimal("100.0"),
            ledgerUnitTotals = emptyMap(),
            expenseTotals = emptyMap(),
        ),
    ),
) : ParticipantExpenseShareRepository {
    override suspend fun getForActivity(activityId: String, currentUserId: String) = result

    override suspend fun getForLedgerUnit(
        activityId: String,
        ledgerUnitId: String,
        currentUserId: String,
    ) = result
}
