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
import com.ffocalors.sharedledger.data.activity.toUiKind
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepository
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareRepositoryFactory
import com.ffocalors.sharedledger.data.expense.ParticipantExpenseShareSnapshot
import com.ffocalors.sharedledger.data.expense.ExpenseOperationException
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
import com.ffocalors.sharedledger.ui.screens.ActivityManagementParticipant
import com.ffocalors.sharedledger.ui.screens.ActivityManagementStatus
import com.ffocalors.sharedledger.ui.screens.ActivityManagementUiState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class ActivityHomeUiState(
    val isLoading: Boolean = true,
    val activities: List<ActivityCardUiModel> = emptyList(),
    val errorMessage: String? = null,
)

data class ActivityDetailUiState(
    val isLoading: Boolean = true,
    val detail: ActivityDetail? = null,
    val errorMessage: String? = null,
)

class ActivityViewModel(
    private val repository: ActivityRepository,
    private val currentUserId: String,
    private val participantExpenseShareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
) : ViewModel() {
    private val _home = MutableStateFlow(ActivityHomeUiState())
    val home: StateFlow<ActivityHomeUiState> = _home.asStateFlow()
    private val detailStates = mutableMapOf<String, MutableStateFlow<ActivityDetailUiState>>()
    private val _join = MutableStateFlow(JoinActivityUiState())
    val join: StateFlow<JoinActivityUiState> = _join.asStateFlow()
    private var joinedActivityIdValue: String? = null
    private val _actionLoading = MutableStateFlow(false)
    val actionLoading: StateFlow<Boolean> = _actionLoading.asStateFlow()
    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()

    fun detail(activityId: String): StateFlow<ActivityDetailUiState> = detailStates.getOrPut(activityId) {
        MutableStateFlow(ActivityDetailUiState())
    }.asStateFlow()

    fun clearMessage() { _message.value = null }

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
        if (!force && !_home.value.isLoading && _home.value.activities.isNotEmpty()) return
        viewModelScope.launch {
            _home.value = ActivityHomeUiState(isLoading = true)
            repository.listActivities().fold(
                onSuccess = { summaries ->
                    val cards = mutableListOf<ActivityCardUiModel>()
                    for (summary in summaries) {
                        val sharesResult = participantExpenseShareRepository
                            .getForActivity(summary.id, currentUserId)
                        if (sharesResult.isFailure) {
                            _home.value = ActivityHomeUiState(
                                isLoading = false,
                                errorMessage = participantShareMessage(sharesResult.exceptionOrNull()),
                            )
                            return@launch
                        }
                        cards += toCard(summary, sharesResult.getOrNull())
                    }
                    _home.value = ActivityHomeUiState(false, cards)
                },
                onFailure = { _home.value = ActivityHomeUiState(false, errorMessage = messageFor(it)) },
            )
        }
    }

    fun refreshHome() = loadHome(force = true)

    fun resetJoin() {
        joinedActivityIdValue = null
        _join.value = JoinActivityUiState()
    }

    fun loadDetail(activityId: String, force: Boolean = false) {
        val state = detailStates.getOrPut(activityId) { MutableStateFlow(ActivityDetailUiState()) }
        if (!force && !state.value.isLoading && state.value.detail != null) return
        viewModelScope.launch {
            state.value = ActivityDetailUiState(isLoading = true, detail = state.value.detail)
            repository.getActivity(activityId).fold(
                onSuccess = { state.value = ActivityDetailUiState(false, it) },
                onFailure = { error ->
                    val kind = (error as? ActivityOperationException)?.kind
                    val keepCachedDetail = kind != ActivityFailureKind.PermissionDenied &&
                        kind != ActivityFailureKind.NotFound
                    state.value = ActivityDetailUiState(
                        isLoading = false,
                        detail = state.value.detail.takeIf { keepCachedDetail },
                        errorMessage = messageFor(error),
                    )
                },
            )
        }
    }

    fun createActivity(name: String, kind: com.ffocalors.sharedledger.ui.components.ActivityKind, multiCurrency: Boolean, onSuccess: (ActivitySummary) -> Unit) {
        if (name.isBlank() || _actionLoading.value) return
        _actionLoading.value = true
        viewModelScope.launch {
            try {
                repository.createActivity(name, if (kind == com.ffocalors.sharedledger.ui.components.ActivityKind.Large) ActivityType.Large else ActivityType.Normal, "CNY", multiCurrency)
                    .fold({ _message.value = "活动已创建"; loadHome(force = true); onSuccess(it) }, { _message.value = messageFor(it) })
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
                onSuccess = { _join.value = _join.value.copy(status = JoinActivityStatus.Joined); loadHome(); loadDetail(activityId, true); onSuccess() },
                onFailure = { _message.value = messageFor(it); _join.value = _join.value.copy(status = JoinActivityStatus.ReadyToJoin) },
            )
            _actionLoading.value = false
        }
    }

    fun unclaimParticipant(activityId: String) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.unclaimParticipant(activityId).fold({ loadDetail(activityId, true); _message.value = "已解除参与人认领" }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun bindCurrentUser(activityId: String, participantId: String) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            repository.claimParticipant(activityId, participantId).fold(
                onSuccess = {
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
            repository.createParticipant(activityId, name).fold({ loadDetail(activityId, true); _message.value = "参与人已添加" }, { _message.value = messageFor(it) })
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
            repository.createSubActivity(activityId, name).fold({ loadDetail(activityId, true); _message.value = "子活动已创建"; onSuccess() }, { _message.value = messageFor(it) })
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
            repository.updateSettings(activityId, name, baseCurrency, multiCurrency).fold({ loadDetail(activityId, true); _message.value = "活动设置已保存" }, { _message.value = messageFor(it) })
            _actionLoading.value = false
        }
    }

    fun unarchiveActivity(activityId: String) = lifecycleAction(activityId) { repository.unarchiveActivity(activityId) }

    fun transferCreator(activityId: String, newCreatorUserId: String) = lifecycleAction(activityId) {
        repository.transferCreator(activityId, newCreatorUserId)
    }

    fun archiveActivity(activityId: String, onSuccess: () -> Unit = {}) = lifecycleAction(activityId, onSuccess) { repository.archiveActivity(activityId) }
    fun deleteActivity(activityId: String, onSuccess: () -> Unit = {}) = lifecycleAction(activityId, onSuccess) { repository.deleteActivity(activityId) }
    fun removeMember(activityId: String, userId: String) = lifecycleAction(activityId) { repository.removeMember(activityId, userId) }

    private fun isParticipantListLocked(activityId: String): Boolean =
        detailStates[activityId]?.value?.detail?.summary?.participantsLockedAt != null

    private fun isActivityArchived(activityId: String): Boolean =
        detailStates[activityId]?.value?.detail?.summary?.archivedAt != null

    private fun lifecycleAction(activityId: String, onSuccess: () -> Unit = {}, block: suspend () -> Result<Unit>) {
        if (_actionLoading.value) return
        viewModelScope.launch {
            _actionLoading.value = true
            block().fold({ loadHome(force = true); loadDetail(activityId, force = true); _message.value = "操作已完成"; onSuccess() }, { _message.value = messageFor(it) })
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

    class Factory(
        private val repository: ActivityRepository = ActivityRepositoryFactory.create(),
        private val currentUserId: String,
        private val participantExpenseShareRepository: ParticipantExpenseShareRepository = ParticipantExpenseShareRepositoryFactory.create(),
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = ActivityViewModel(
            repository,
            currentUserId,
            participantExpenseShareRepository,
        ) as T
    }
}
