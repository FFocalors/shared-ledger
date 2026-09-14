package com.ffocalors.sharedledger.ui.activity

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ffocalors.sharedledger.data.activity.ActivityDetail
import com.ffocalors.sharedledger.data.activity.ActivityErrorMapper
import com.ffocalors.sharedledger.data.activity.ActivityOperationException
import com.ffocalors.sharedledger.data.activity.ActivityFailureKind
import com.ffocalors.sharedledger.data.activity.ActivityRepository
import com.ffocalors.sharedledger.data.activity.ActivityRepositoryFactory
import com.ffocalors.sharedledger.data.activity.ActivitySummary
import com.ffocalors.sharedledger.data.activity.ActivityType
import com.ffocalors.sharedledger.data.activity.mapConcurrentlyPreservingOrder
import com.ffocalors.sharedledger.data.activity.toUiKind
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepository
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepositoryFactory
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareSnapshot
import com.ffocalors.sharedledger.data.expense.ExpenseOperationException
import com.ffocalors.sharedledger.data.exchange.ExchangeRateRepository
import com.ffocalors.sharedledger.data.exchange.ExchangeRate
import com.ffocalors.sharedledger.data.exchange.SupportedExchangeCurrency
import com.ffocalors.sharedledger.ui.components.ActivityCardUiModel
import com.ffocalors.sharedledger.ui.components.ActivityStatus
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SubActivityUiModel
import com.ffocalors.sharedledger.ui.theme.IconContainerSage
import com.ffocalors.sharedledger.ui.theme.WarmOrangeContainer
import com.ffocalors.sharedledger.ui.util.UiDateTimeFormatter
import com.ffocalors.sharedledger.ui.screens.JoinActivityParticipant
import com.ffocalors.sharedledger.ui.screens.JoinActivityPreview
import com.ffocalors.sharedledger.ui.screens.JoinActivityStatus
import com.ffocalors.sharedledger.ui.screens.JoinActivityUiState
import com.ffocalors.sharedledger.ui.screens.ActivityManagementMember
import com.ffocalors.sharedledger.ui.screens.ActivityManagementDeletedSubActivity
import com.ffocalors.sharedledger.ui.screens.ActivityManagementParticipant
import com.ffocalors.sharedledger.ui.screens.ActivityManagementStatus
import com.ffocalors.sharedledger.ui.screens.ActivityManagementUiState
import com.ffocalors.sharedledger.ui.profile.PersonalOverview
import com.ffocalors.sharedledger.ui.profile.PersonalOverviewUiState
import com.ffocalors.sharedledger.ui.profile.mapPersonalOverview
import com.ffocalors.sharedledger.ui.cache.QueryCacheKey
import com.ffocalors.sharedledger.ui.cache.QueryCacheState
import com.ffocalors.sharedledger.ui.cache.SessionQueryCache
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class ActivityHomeUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val activities: List<ActivityCardUiModel> = emptyList(),
    val errorMessage: String? = null,
)

data class ActivityDetailUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val detail: ActivityDetail? = null,
    val errorMessage: String? = null,
)

class ActivityViewModel(
    private val repository: ActivityRepository,
    private val currentUserId: String,
    private val participantExpenseShareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
    private val queryCache: SessionQueryCache = SessionQueryCache(),
    private val exchangeRateRepository: ExchangeRateRepository? = null,
) : ViewModel() {
    private val _home = MutableStateFlow(ActivityHomeUiState())
    val home: StateFlow<ActivityHomeUiState> = _home.asStateFlow()
    private val detailStates = mutableMapOf<String, MutableStateFlow<ActivityDetailUiState>>()
    private val _join = MutableStateFlow(JoinActivityUiState())
    val join: StateFlow<JoinActivityUiState> = _join.asStateFlow()
    private var joinedActivityIdValue: String? = null
    // A confirmed delete must win over any read that was already in flight.
    private val deletedActivityIds = mutableSetOf<String>()
    private val _actionLoading = MutableStateFlow(false)
    val actionLoading: StateFlow<Boolean> = _actionLoading.asStateFlow()
    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()
    private val _personalOverview = MutableStateFlow(PersonalOverviewUiState())
    val personalOverview: StateFlow<PersonalOverviewUiState> = _personalOverview.asStateFlow()
    private var personalOverviewLoadInFlight = false
    private val _supportedCurrencies = MutableStateFlow<List<SupportedExchangeCurrency>>(emptyList())
    val supportedCurrencies: StateFlow<List<SupportedExchangeCurrency>> = _supportedCurrencies.asStateFlow()
    private val _exchangeRates = MutableStateFlow<Map<String, ExchangeRate>>(emptyMap())
    val exchangeRates: StateFlow<Map<String, ExchangeRate>> = _exchangeRates.asStateFlow()
    private val exchangeRateSyncMutex = Mutex()

    fun detail(activityId: String): StateFlow<ActivityDetailUiState> = detailStates.getOrPut(activityId) {
        MutableStateFlow(ActivityDetailUiState())
    }.asStateFlow()

    fun clearMessage() { _message.value = null }

    fun refreshExchangeRates() {
        val repository = exchangeRateRepository ?: return
        viewModelScope.launch {
            refreshExchangeRateCache(repository)
        }
    }

    fun refreshExchangeRate(baseCurrency: String, quoteCurrency: String) {
        val repository = exchangeRateRepository ?: return
        val base = baseCurrency.trim().uppercase()
        val quote = quoteCurrency.trim().uppercase()
        if (base.isBlank() || quote.isBlank()) return
        viewModelScope.launch {
            // Always re-read the selected pair after the server refresh. This
            // avoids racing a stale local/server read against the Edge sync.
            refreshExchangeRateCache(repository)
            repository.getRate(base, quote).onSuccess { rate ->
                _exchangeRates.value = _exchangeRates.value + ("$base:$quote" to rate)
            }
        }
    }

    private suspend fun refreshExchangeRateCache(repository: ExchangeRateRepository) {
        exchangeRateSyncMutex.withLock {
            repository.syncExchangeRates()
            repository.listSupportedCurrencies().onSuccess { _supportedCurrencies.value = it }
        }
    }

    fun loadExchangeRate(baseCurrency: String, quoteCurrency: String) {
        val repository = exchangeRateRepository ?: return
        val base = baseCurrency.trim().uppercase()
        val quote = quoteCurrency.trim().uppercase()
        if (base.isBlank() || quote.isBlank()) return
        viewModelScope.launch {
            repository.getRate(base, quote).onSuccess { rate ->
                _exchangeRates.value = _exchangeRates.value + ("$base:$quote" to rate)
            }
        }
    }

    fun loadCachedExchangeRates(baseCurrency: String) {
        val repository = exchangeRateRepository ?: return
        val base = baseCurrency.trim().uppercase()
        if (base.isBlank()) return
        viewModelScope.launch {
            repository.readCachedRates(base).onSuccess { rates ->
                _exchangeRates.value = _exchangeRates.value + rates.associateBy { rate ->
                    "${base}:${rate.quoteCurrency.trim().uppercase()}"
                }
            }
        }
    }

    fun selectJoinParticipant(participantId: String, participantName: String?) {
        _join.value = _join.value.copy(
            selectedParticipantId = participantId,
            selectedParticipantName = participantName,
        )
    }

    fun joinedActivityId(): String? = joinedActivityIdValue

    /**
     * join_activity_by_code already creates the ActivityMember. Claiming a
     * Participant is optional, so an empty participant list must still be
     * able to complete the join flow.
     */
    fun completeJoinWithoutClaim(onSuccess: () -> Unit = {}) {
        if (_actionLoading.value || joinedActivityIdValue == null) return
        if (_join.value.status != JoinActivityStatus.ReadyToJoin) return
        _join.value = _join.value.copy(status = JoinActivityStatus.Joined)
        loadHome(force = true)
        onSuccess()
    }

    fun managementState(activityId: String): ActivityManagementUiState? =
        detailStates[activityId]?.value?.detail?.let { detail ->
            val currentUser = detail.members.firstOrNull { it.userId == currentUserId }
            val currentClaim = currentUser?.claimedParticipantId
                ?.let { claimedId -> detail.participants.firstOrNull { it.id == claimedId } }
            val isArchived = detail.summary.archivedAt != null
            val canManageParticipants = detail.permissions.canManageParticipants && !isArchived
            val canManageMembers = detail.permissions.canManageMembers && !isArchived
            val canEditSettings = detail.permissions.canEditSettings && !isArchived
            val canArchive = detail.permissions.canArchive && !isArchived
            ActivityManagementUiState(
                activityName = detail.summary.name,
                activityType = if (detail.summary.type == ActivityType.Large) "大型活动" else "普通活动",
                baseCurrency = "${detail.summary.baseCurrency} (¥)",
                multiCurrencyEnabled = detail.summary.multiCurrencyEnabled,
                joinCode = detail.summary.joinCode.chunked(4).joinToString(" "),
                participants = detail.participants.map { participant ->
                    ActivityManagementParticipant(
                        name = participant.name,
                        initial = participant.name.take(1),
                        isBound = participant.claimedUserId != null,
                        participantId = participant.id,
                        boundUserName = participant.claimedUserName,
                        isBoundToCurrentUser = participant.claimedUserId == currentUserId,
                    )
                },
                members = detail.members.map { member ->
                    ActivityManagementMember(
                        name = member.displayName,
                        initial = member.displayName.take(1),
                        role = if (member.isCreator) "创建者" else "用户",
                        detail = member.claimedParticipantId?.let { claimed ->
                            "绑定参与人: ${detail.participants.firstOrNull { it.id == claimed }?.name.orEmpty()}"
                        } ?: "未绑定参与人",
                        isCreator = member.isCreator,
                        memberId = member.userId,
                    )
                },
                deletedSubActivities = if (detail.summary.type == ActivityType.Large) {
                    detail.deletedLedgerUnits.map { unit ->
                        ActivityManagementDeletedSubActivity(
                            name = unit.name,
                            ledgerUnitId = unit.id,
                            deletedAt = unit.deletedAt?.let(UiDateTimeFormatter::format),
                        )
                    }
                } else {
                    emptyList()
                },
                status = when {
                    detail.summary.archivedAt != null -> ActivityManagementStatus.Archived
                    detail.summary.status.name == "Completed" -> ActivityManagementStatus.Settled
                    else -> ActivityManagementStatus.InProgress
                },
                outstandingDebt = "${detail.summary.baseCurrency} ${detail.summary.totalDebt}",
                hasOutstandingDebt = detail.summary.totalDebt.toBigDecimalOrNull()?.signum() == 1,
                remainingPrepayment = "${detail.summary.baseCurrency} ${detail.summary.totalPrepayment}",
                participantListLocked = detail.summary.participantsLockedAt != null,
                participantListLockMessage = if (detail.summary.participantsLockedAt != null) {
                    "参与人名单已锁定，不能新增或删除参与人；仍可绑定或解除绑定。"
                } else {
                    ""
                },
                showSettings = canEditSettings,
                showLeaveAction = detail.summary.createdBy != currentUserId && !isArchived,
                showDeleteAction = detail.permissions.canDelete && !isArchived,
                showTransferOwnershipAction = detail.summary.createdBy == currentUserId && canManageMembers,
                currentUserName = currentUser?.displayName.orEmpty(),
                currentUserParticipantId = currentClaim?.id,
                currentUserParticipantName = currentClaim?.name,
                canManageParticipants = canManageParticipants,
                canManageMembers = canManageMembers,
                canArchiveActivity = canArchive,
                canUnarchiveActivity = detail.permissions.canArchive && isArchived,
                canBindParticipant = currentUser != null && currentClaim == null && !isArchived,
                canUnbindParticipant = currentUser != null && currentClaim != null && !isArchived,
            )
        }

    fun loadHome(force: Boolean = false) {
        val key = homeCacheKey()
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            _home.value = ActivityHomeUiState(
                isLoading = false,
                isRefreshing = false,
                activities = cached.value.filterNot { it.activityId in deletedActivityIds },
            )
            return
        }
        val existing = (cached.value ?: _home.value.activities)
            .filterNot { it.activityId in deletedActivityIds }
        viewModelScope.launch {
            _home.value = _home.value.copy(
                isLoading = existing.isEmpty(),
                isRefreshing = existing.isNotEmpty(),
                activities = existing,
                errorMessage = null,
            )
            val result = queryCache.getOrLoad(key, forceRefresh = true) {
                repository.listActivities().fold(
                    onSuccess = { summaries ->
                        val visibleSummaries = summaries.filterNot { it.id in deletedActivityIds }
                        val cardResults = mapConcurrentlyPreservingOrder(
                            visibleSummaries,
                            maxConcurrency = 4,
                        ) { summary ->
                            participantExpenseShareRepository.getForActivity(summary.id, currentUserId).fold(
                                onSuccess = { Result.success(toCard(summary, it)) },
                                onFailure = {
                                    Result.failure<ActivityCardUiModel>(
                                        ExpenseOperationException("我的应承担金额加载失败，请重试", it),
                                    )
                                },
                            )
                        }
                        val firstFailure = cardResults.indexOfFirst { it.isFailure }
                        if (firstFailure >= 0) {
                            Result.failure(cardResults[firstFailure].exceptionOrNull()!!)
                        } else {
                            Result.success(cardResults.map { it.getOrThrow() }
                                .filterNot { it.activityId in deletedActivityIds })
                        }
                    },
                    onFailure = { Result.failure(it) },
                )
            }
            result.fold(
                onSuccess = { cards ->
                    _home.value = ActivityHomeUiState(
                        isLoading = false,
                        isRefreshing = false,
                        activities = cards.filterNot { it.activityId in deletedActivityIds },
                    )
                },
                onFailure = { error ->
                    _home.value = _home.value.copy(
                        isLoading = false,
                        isRefreshing = false,
                        activities = existing,
                        errorMessage = participantShareMessage(error).takeIf { error is ExpenseOperationException }
                            ?: messageFor(error),
                    )
                },
            )
        }
    }

    fun refreshHome() = loadHome(force = true)

    fun refreshPersonalOverview() {
        if (personalOverviewLoadInFlight) return
        val key = personalOverviewCacheKey()
        val cached = queryCache.read(key)
        if (cached.state == QueryCacheState.Fresh && cached.value != null && _personalOverview.value.overview == null) {
            _personalOverview.value = PersonalOverviewUiState(
                isLoading = false,
                isRefreshing = false,
                overview = cached.value,
            )
            return
        }
        personalOverviewLoadInFlight = true
        viewModelScope.launch {
            val cachedOverview = cached.value ?: _personalOverview.value.overview
            _personalOverview.value = PersonalOverviewUiState(
                isLoading = cachedOverview == null,
                isRefreshing = cachedOverview != null,
                overview = cachedOverview,
            )
            try {
                val result = queryCache.getOrLoad(key, forceRefresh = true) {
                    val summariesResult = repository.listActivities()
                    if (summariesResult.isFailure) return@getOrLoad Result.failure(summariesResult.exceptionOrNull()!!)
                    val summaries = summariesResult.getOrThrow()
                        .filterNot { it.id in deletedActivityIds }
                    val detailResults = mapConcurrentlyPreservingOrder(
                        summaries,
                        maxConcurrency = 4,
                    ) { summary -> repository.getActivity(summary.id) }
                    val firstFailure = detailResults.indexOfFirst { it.isFailure }
                    if (firstFailure >= 0) {
                        val summary = summaries[firstFailure]
                        val error = detailResults[firstFailure].exceptionOrNull()!!
                        return@getOrLoad Result.failure(
                            IllegalStateException(
                                "活动「${summary.name}」加载失败：${messageFor(error)}",
                                error,
                            ),
                        )
                    }
                    val details = detailResults.map { it.getOrThrow() }
                    Result.success(mapPersonalOverview(currentUserId, details))
                }
                result.fold(
                    onSuccess = { overview ->
                        _personalOverview.value = PersonalOverviewUiState(
                            isLoading = false,
                            isRefreshing = false,
                            overview = overview,
                        )
                    },
                    onFailure = { error ->
                        _personalOverview.value = PersonalOverviewUiState(
                            isLoading = false,
                            isRefreshing = false,
                            overview = cachedOverview,
                            errorMessage = error.message?.takeIf { it.startsWith("活动「") }
                                ?: messageFor(error),
                        )
                    },
                )
            } finally {
                personalOverviewLoadInFlight = false
            }
        }
    }

    fun resetJoin() {
        joinedActivityIdValue = null
        _join.value = JoinActivityUiState()
    }

    fun loadDetail(activityId: String, force: Boolean = false) {
        val state = detailStates.getOrPut(activityId) { MutableStateFlow(ActivityDetailUiState()) }
        if (activityId in deletedActivityIds) {
            state.value = ActivityDetailUiState(
                isLoading = false,
                detail = null,
                errorMessage = "活动已删除",
            )
            return
        }
        val key = detailCacheKey(activityId)
        val cached = queryCache.read(key)
        if (!force && cached.state == QueryCacheState.Fresh && cached.value != null) {
            state.value = ActivityDetailUiState(
                isLoading = false,
                isRefreshing = false,
                detail = cached.value,
            )
            return
        }
        val existing = cached.value ?: state.value.detail
        viewModelScope.launch {
            state.value = state.value.copy(
                isLoading = existing == null,
                isRefreshing = existing != null,
                detail = existing,
                errorMessage = null,
            )
            val result = queryCache.getOrLoad(key, forceRefresh = true) { repository.getActivity(activityId) }
            result.fold(
                onSuccess = {
                    if (activityId in deletedActivityIds) {
                        state.value = ActivityDetailUiState(
                            isLoading = false,
                            detail = null,
                            errorMessage = "活动已删除",
                        )
                        return@fold
                    }
                    state.value = ActivityDetailUiState(
                        isLoading = false,
                        isRefreshing = false,
                        detail = it,
                    )
                },
                onFailure = { error ->
                    val kind = (error as? ActivityOperationException)?.kind
                    val keepCachedDetail = kind != ActivityFailureKind.PermissionDenied &&
                        kind != ActivityFailureKind.NotFound
                    if (!keepCachedDetail) clearActivitySessionData(activityId, messageFor(error))
                    state.value = ActivityDetailUiState(
                        isLoading = false,
                        detail = existing.takeIf { keepCachedDetail },
                        errorMessage = messageFor(error),
                    )
                },
            )
        }
    }

    fun createActivity(name: String, kind: com.ffocalors.sharedledger.ui.components.ActivityKind, multiCurrency: Boolean, baseCurrency: String = "CNY", onSuccess: (ActivitySummary) -> Unit) {
        if (name.isBlank() || _actionLoading.value) return
        _actionLoading.value = true
        viewModelScope.launch {
            try {
                repository.createActivity(name, if (kind == com.ffocalors.sharedledger.ui.components.ActivityKind.Large) ActivityType.Large else ActivityType.Normal, baseCurrency, multiCurrency)
                    .fold({ invalidateSessionCaches(); _message.value = "活动已创建"; loadHome(force = true); onSuccess(it) }, { _message.value = messageFor(it) })
            } finally {
                _actionLoading.value = false
            }
        }
    }

    fun joinActivity(code: String) {
        if (code.length != 8 || _actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            _join.value = _join.value.copy(inviteCode = code, status = JoinActivityStatus.Joining)
            repository.joinActivity(code).fold(
                onSuccess = { detail -> joinedActivityIdValue = detail.summary.id; _join.value = toJoinState(detail) },
                onFailure = { _join.value = _join.value.copy(status = JoinActivityStatus.InvalidCode); _message.value = messageFor(it) },
            )
            _actionLoading.value = false
        }
    }

    fun claimParticipant(activityId: String, participantId: String, onSuccess: () -> Unit = {}) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.claimParticipant(activityId, participantId).fold(
                onSuccess = { invalidateActivityCaches(activityId); _join.value = _join.value.copy(status = JoinActivityStatus.Joined); loadHome(); loadDetail(activityId, true); onSuccess() },
                onFailure = { _message.value = messageFor(it); _join.value = _join.value.copy(status = JoinActivityStatus.ReadyToJoin) },
            )
            _actionLoading.value = false
        }
    }

    fun unclaimParticipant(activityId: String) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.unclaimParticipant(activityId).fold({ invalidateActivityCaches(activityId); loadDetail(activityId, true); _message.value = "已解除参与人认领" }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun bindCurrentUser(activityId: String, participantId: String) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.claimParticipant(activityId, participantId).fold(
                onSuccess = {
                    invalidateActivityCaches(activityId)
                    loadDetail(activityId, force = true)
                    _message.value = "已绑定参与人"
                },
                onFailure = { _message.value = messageFor(it) },
            )
            _actionLoading.value = false
        }
    }

    fun unbindCurrentUser(activityId: String) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.unclaimParticipant(activityId).fold(
                onSuccess = {
                    invalidateActivityCaches(activityId)
                    loadDetail(activityId, force = true)
                    _message.value = "已解除参与人绑定"
                },
                onFailure = { _message.value = messageFor(it) },
            )
            _actionLoading.value = false
        }
    }

    fun isCurrentUserBound(detail: ActivityDetail?): Boolean =
        detail?.members?.any { it.userId == currentUserId && it.claimedParticipantId != null } == true

    fun deleteParticipant(participantId: String, activityId: String) = lifecycleAction(activityId) {
        if (isActivityArchived(activityId)) {
            _message.value = "活动已归档，当前为只读状态"
            return@lifecycleAction Result.failure(ActivityOperationException("活动已归档，当前为只读状态"))
        }
        if (isParticipantListLocked(activityId)) {
            _message.value = "参与人名单已锁定，不能删除参与人"
            return@lifecycleAction Result.failure(ActivityOperationException("参与人名单已锁定，不能删除参与人"))
        }
        val participant = detailStates[activityId]?.value?.detail?.participants
            ?.firstOrNull { it.id == participantId }
        if (participant?.claimedUserId != null) {
            _message.value = "已绑定参与人不能删除，请先解除绑定"
            return@lifecycleAction Result.failure(ActivityOperationException("已绑定参与人不能删除，请先解除绑定"))
        }
        repository.deleteParticipant(participantId)
    }

    fun createParticipant(activityId: String, name: String) {
        if (name.isBlank() || _actionLoading.value) return
        if (isParticipantListLocked(activityId)) {
            _message.value = "参与人名单已锁定，不能新增参与人"
            return
        }
        viewModelScope.launch {
            _actionLoading.value = true
            repository.createParticipant(activityId, name).fold({ invalidateActivityCaches(activityId); loadDetail(activityId, true); _message.value = "参与人已添加" }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun createSubActivity(activityId: String, name: String, onSuccess: () -> Unit = {}) {
        if (name.isBlank() || _actionLoading.value) return
        if (isActivityArchived(activityId)) {
            _message.value = "活动已归档，当前为只读状态"
            return
        }
        viewModelScope.launch {
            _actionLoading.value = true
            repository.createSubActivity(activityId, name).fold({ invalidateActivityCaches(activityId); loadDetail(activityId, true); _message.value = "子活动已创建"; onSuccess() }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun updateSettings(activityId: String, name: String, multiCurrency: Boolean) {
        val baseCurrency = detailStates[activityId]?.value?.detail?.summary?.baseCurrency
        if (baseCurrency.isNullOrBlank()) {
            _message.value = "活动基础币种尚未加载，请刷新后重试"
            return
        }
        updateSettings(activityId, name, baseCurrency, multiCurrency)
    }

    fun updateSettings(activityId: String, name: String, baseCurrency: String, multiCurrency: Boolean) {
        if (name.isBlank() || _actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.updateSettings(activityId, name, baseCurrency, multiCurrency).fold({ invalidateActivityCaches(activityId); loadDetail(activityId, true); _message.value = "活动设置已保存" }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun unarchiveActivity(activityId: String) = lifecycleAction(activityId) { repository.unarchiveActivity(activityId) }

    fun transferCreator(activityId: String, newCreatorUserId: String) = lifecycleAction(activityId) {
        repository.transferCreator(activityId, newCreatorUserId)
    }

    fun deleteSubActivity(activityId: String, subActivityId: String, onSuccess: () -> Unit = {}) {
        if (_actionLoading.value) return
        val unit = detailStates[activityId]?.value?.detail?.ledgerUnits?.firstOrNull { it.id == subActivityId }
        if (unit == null || !unit.type.equals("sub_activity", ignoreCase = true)) {
            _message.value = "只能删除大型活动中的子活动"
            return
        }
        if (isActivityArchived(activityId)) {
            _message.value = "活动已归档，当前为只读状态"
            return
        }
        viewModelScope.launch {
            _actionLoading.value = true
            repository.deleteSubActivity(subActivityId).fold(
                onSuccess = {
                    invalidateActivityCaches(activityId)
                    loadDetail(activityId, force = true)
                    _message.value = "子活动已删除，可在活动管理中恢复"
                    onSuccess()
                },
                onFailure = { _message.value = messageFor(it) },
            )
            _actionLoading.value = false
        }
    }

    fun restoreSubActivity(activityId: String, subActivityId: String) {
        if (_actionLoading.value) return
        if (isActivityArchived(activityId)) {
            _message.value = "活动已归档，当前为只读状态"
            return
        }
        viewModelScope.launch {
            _actionLoading.value = true
            repository.restoreSubActivity(subActivityId).fold(
                onSuccess = {
                    invalidateActivityCaches(activityId)
                    loadDetail(activityId, force = true)
                    _message.value = "子活动已恢复"
                },
                onFailure = { _message.value = messageFor(it) },
            )
            _actionLoading.value = false
        }
    }

    fun showMessage(message: String) {
        _message.value = message
    }

    fun archiveActivity(activityId: String, onSuccess: () -> Unit = {}) = lifecycleAction(activityId, onSuccess) { repository.archiveActivity(activityId) }

    /**
     * Deletion is terminal for this session. Do not start the usual detail
     * refresh after the RPC: a confirmed delete is expected to make that read
     * return not-found, which must not be surfaced as a delete failure.
     */
    fun deleteActivity(activityId: String, onSuccess: () -> Unit = {}) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.deleteActivity(activityId).fold(
                onSuccess = {
                    deletedActivityIds += activityId
                    removeDeletedActivitySessionData(activityId)
                    _message.value = "活动已删除"
                    onSuccess()
                },
                onFailure = { error ->
                    // A transport failure can happen after the RPC committed. Keep
                    // the card until confirmation and tell the user the result is
                    // unknown instead of claiming that deletion did not happen.
                    val kind = (error as? ActivityOperationException)?.kind
                    _message.value = if (kind == ActivityFailureKind.Network) {
                        "删除结果未知，请刷新活动列表确认"
                    } else {
                        messageFor(error)
                    }
                    if (kind == ActivityFailureKind.Network) {
                        invalidateActivityCaches(activityId)
                    }
                },
            )
            _actionLoading.value = false
        }
    }
    fun removeMember(activityId: String, userId: String) = lifecycleAction(activityId) { repository.removeMember(activityId, userId) }

    private fun isParticipantListLocked(activityId: String): Boolean =
        detailStates[activityId]?.value?.detail?.summary?.participantsLockedAt != null

    private fun isActivityArchived(activityId: String): Boolean =
        detailStates[activityId]?.value?.detail?.summary?.archivedAt != null

    private fun lifecycleAction(activityId: String, onSuccess: () -> Unit = {}, block: suspend () -> Result<Unit>) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            block().fold({ invalidateActivityCaches(activityId); loadHome(force = true); loadDetail(activityId, force = true); _message.value = "操作已完成"; onSuccess() }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    private fun toCard(summary: ActivitySummary, shares: ParticipantExpenseShareSnapshot?): ActivityCardUiModel = ActivityCardUiModel(
        name = summary.name,
        kind = summary.type.toUiKind(),
        participantCount = summary.participantCount,
        status = if (summary.archivedAt != null) ActivityStatus.Archived else if (summary.status == com.ffocalors.sharedledger.data.activity.ActivityFinancialStatus.Completed) ActivityStatus.Settled else ActivityStatus.InProgress,
        totalAmount = shares?.activityTotalBaseAmount,
        currencyCode = summary.baseCurrency,
        updatedAt = summary.archivedAt?.let(UiDateTimeFormatter::format) ?: "刚刚更新",
        participants = summary.participantNames.mapIndexed { index, name -> ParticipantUiModel(name, if (index % 2 == 0) IconContainerSage else WarmOrangeContainer) },
        activityId = summary.id,
        amountAvailable = shares?.isBound == true,
    )

    private fun toJoinState(detail: ActivityDetail): JoinActivityUiState = JoinActivityUiState(
        inviteCode = detail.summary.joinCode,
        status = JoinActivityStatus.ReadyToJoin,
        preview = JoinActivityPreview(
            name = detail.summary.name,
            kindLabel = if (detail.summary.type == ActivityType.Large) "大型活动" else "普通活动",
            participantCount = detail.participants.size,
            claimedCount = detail.participants.count { it.claimedUserId != null },
            participants = detail.participants.map { participant ->
                JoinActivityParticipant(
                    name = participant.name,
                    state = when {
                        participant.claimedUserId == currentUserId -> com.ffocalors.sharedledger.ui.screens.JoinParticipantState.ClaimedByCurrentUser
                        participant.claimedUserId != null -> com.ffocalors.sharedledger.ui.screens.JoinParticipantState.ClaimedByOther
                        else -> com.ffocalors.sharedledger.ui.screens.JoinParticipantState.Available
                    },
                    participantId = participant.id,
                )
            },
        ),
    )

    private fun messageFor(error: Throwable): String =
        (error as? ActivityOperationException)?.userMessage ?: ActivityErrorMapper.toUserMessage(error)

    private fun participantShareMessage(error: Throwable?): String =
        (error as? ExpenseOperationException)?.userMessage
            ?: "我的应承担金额加载失败，请重试"

    /** Called by the navigation/realtime bridge after an activity read-model change. */
    fun invalidateActivity(activityId: String? = null) {
        if (activityId.isNullOrBlank()) invalidateSessionCaches()
        else invalidateActivityCaches(activityId)
    }

    /** Clears the injected session cache on sign-out/session destruction. */
    fun clearSessionCache() = queryCache.clear()

    /** Remove every scoped read model after access is denied or the activity disappears. */
    private fun clearActivitySessionData(activityId: String, errorMessage: String) {
        removeActivityScopedSessionCaches(activityId)
        _home.value = _home.value.copy(
            activities = _home.value.activities.filterNot { it.activityId == activityId },
        )
        _personalOverview.value = PersonalOverviewUiState(
            isLoading = false,
            errorMessage = errorMessage,
        )
    }

    private fun removeDeletedActivitySessionData(activityId: String) {
        removeActivityScopedSessionCaches(activityId)
        _home.value = _home.value.copy(
            activities = _home.value.activities.filterNot { it.activityId == activityId },
            errorMessage = null,
        )
        detailStates[activityId]?.value = ActivityDetailUiState(
            isLoading = false,
            detail = null,
            errorMessage = "活动已删除",
        )
        // The overview is derived from activity details; do not retain counts
        // that include the deleted activity until the next explicit refresh.
        _personalOverview.value = PersonalOverviewUiState()
    }

    private fun removeActivityScopedSessionCaches(activityId: String) {
        queryCache.remove(detailCacheKey(activityId))
        queryCache.remove(homeCacheKey())
        queryCache.remove(personalOverviewCacheKey())
        queryCache.removePrefix("expense-query:$currentUserId:activity:$activityId")
        // Detail keys predate activity scoping; clear them conservatively on access loss.
        queryCache.removePrefix("expense-query:$currentUserId:detail:")
        queryCache.removePrefix("financial-query:list:$activityId")
        queryCache.removePrefix("financial-query:detail:$activityId:")
        queryCache.removePrefix("financial-query:context:$activityId")
        queryCache.removePrefix("financial-query:preview:$activityId")
        queryCache.removePrefix("transfer-query:$activityId:")
        queryCache.removePrefix("attachment-query:$activityId:")
    }

    private fun homeCacheKey() = QueryCacheKey<List<ActivityCardUiModel>>("activity-query:$currentUserId:home")
    private fun personalOverviewCacheKey() = QueryCacheKey<PersonalOverview>("activity-query:$currentUserId:overview")
    private fun detailCacheKey(activityId: String) = QueryCacheKey<ActivityDetail>("activity-query:$currentUserId:detail:$activityId")

    private fun invalidateActivityCaches(activityId: String) {
        queryCache.invalidate(homeCacheKey())
        queryCache.invalidate(personalOverviewCacheKey())
        queryCache.invalidate(detailCacheKey(activityId))
        queryCache.invalidatePrefix("expense-query:$currentUserId:")
        queryCache.invalidatePrefix("financial-query:list:$activityId")
        queryCache.invalidatePrefix("financial-query:detail:$activityId:")
        queryCache.invalidatePrefix("financial-query:context:$activityId")
        queryCache.invalidatePrefix("financial-query:preview:$activityId")
        queryCache.invalidatePrefix("transfer-query:$activityId:")
        queryCache.invalidatePrefix("attachment-query:$activityId:")
    }

    private fun invalidateSessionCaches() {
        queryCache.invalidatePrefix("activity-query:$currentUserId:")
        queryCache.invalidatePrefix("expense-query:$currentUserId:")
    }

    class Factory(
        private val repository: ActivityRepository = ActivityRepositoryFactory.create(),
        private val currentUserId: String,
        private val participantExpenseShareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
        private val queryCache: SessionQueryCache = SessionQueryCache(),
        private val exchangeRateRepository: ExchangeRateRepository? = null,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = ActivityViewModel(
            repository,
            currentUserId,
            participantExpenseShareRepository,
            queryCache,
            exchangeRateRepository,
        ) as T
    }
}
