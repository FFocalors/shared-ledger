package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ArrowForward
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material.icons.rounded.FlightTakeoff
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ffocalors.sharedledger.R
import com.ffocalors.sharedledger.ui.theme.AppBackground
import com.ffocalors.sharedledger.ui.theme.AppSurfaceLow
import com.ffocalors.sharedledger.ui.theme.AppSurfaceVariant
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerElevation
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerButtonVariant

private val ActivityBottomBarColor = Color(0xFFEFEDED)

enum class JoinActivityStatus {
    Input,
    Loading,
    InvalidCode,
    Deleted,
    AlreadyJoined,
    ReadyToJoin,
    Joining,
    Joined,
}

enum class JoinParticipantState {
    ClaimedByOther,
    ClaimedByCurrentUser,
    Available,
}

data class JoinActivityParticipant(
    val name: String,
    val state: JoinParticipantState = JoinParticipantState.Available,
    val participantId: String = "",
)

data class JoinActivityPreview(
    val name: String = "日本关西秋季行",
    val kindLabel: String = "大型活动",
    val dateRange: String = "2023.10.15 - 10.25",
    val participantCount: Int = 8,
    val claimedCount: Int = 5,
    val participants: List<JoinActivityParticipant> = listOf(
        JoinActivityParticipant("王五", JoinParticipantState.ClaimedByOther, "demo-participant-wangwu"),
        JoinActivityParticipant("张三", JoinParticipantState.ClaimedByCurrentUser, "demo-participant-zhangsan"),
        JoinActivityParticipant("李四", JoinParticipantState.Available, "demo-participant-lisi"),
    ),
)

data class JoinActivityUiState(
    val inviteCode: String = "",
    val status: JoinActivityStatus = JoinActivityStatus.Input,
    val preview: JoinActivityPreview = JoinActivityPreview(),
    val selectedParticipantName: String? = null,
    val selectedParticipantId: String? = null,
)

/**
 * Controlled join-activity flow. The host owns validation, joining, and
 * navigation; this screen only renders the supplied state and emits events.
 */
@Composable
fun JoinActivityScreen(
    state: JoinActivityUiState = JoinActivityUiState(),
    modifier: Modifier = Modifier,
    onBackClick: () -> Unit = {},
    onInviteCodeChange: (String) -> Unit = {},
    onValidateInviteCode: (String) -> Unit = {},
    onParticipantSelected: (String) -> Unit = {},
    onJoinActivity: (String) -> Unit = {},
    onJoinSuccessNavigate: () -> Unit = {},
) {
    LaunchedEffect(state.status) {
        if (state.status == JoinActivityStatus.Joined) {
            onJoinSuccessNavigate()
        }
    }

    val isConfirmState = state.status == JoinActivityStatus.ReadyToJoin ||
        state.status == JoinActivityStatus.Joining ||
        state.status == JoinActivityStatus.Joined

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = AppBackground,
        topBar = {
            JoinActivityTopBar(onBackClick = onBackClick)
        },
        bottomBar = {
            if (isConfirmState) {
                JoinActivityBottomBar(
                    state = state,
                    onJoinActivity = onJoinActivity,
                )
            }
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .verticalScroll(rememberScrollState())
                .padding(innerPadding)
                .padding(
                    horizontal = SharedLedgerDimens.PageHorizontalPadding,
                    vertical = SharedLedgerSpacing.Medium,
                )
                .padding(bottom = SharedLedgerSpacing.Large),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
        ) {
            if (isConfirmState) {
                JoinActivityConfirmation(
                    state = state,
                    onParticipantSelected = onParticipantSelected,
                )
            } else {
                JoinActivityCodeEntry(
                    state = state,
                    onInviteCodeChange = onInviteCodeChange,
                    onValidateInviteCode = onValidateInviteCode,
                )
            }
        }
    }
}

@Composable
private fun JoinActivityTopBar(onBackClick: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = AppBackground.copy(alpha = 0.94f),
    ) {
        Row(
            modifier = Modifier
                .statusBarsPadding()
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxWidth()
                .height(64.dp)
                .padding(horizontal = SharedLedgerDimens.PageHorizontalPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onBackClick,
                modifier = Modifier
                    .size(SharedLedgerDimens.TopBarActionSize)
                    .semantics { contentDescription = "返回" },
            ) {
                Icon(
                    imageVector = Icons.Rounded.ArrowBack,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurface,
                )
            }
            Box(
                modifier = Modifier.weight(1f),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "加入活动",
                    style = SharedLedgerTextStyles.CardTitle,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            Spacer(modifier = Modifier.size(SharedLedgerDimens.TopBarActionSize))
        }
    }
}

@Composable
private fun JoinActivityCodeEntry(
    state: JoinActivityUiState,
    onInviteCodeChange: (String) -> Unit,
    onValidateInviteCode: (String) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall)) {
            Text(
                text = "输入邀请码",
                style = SharedLedgerTextStyles.CardTitle,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "向活动创建者获取 8 位数字邀请码以加入账本。",
                style = SharedLedgerTextStyles.BodySecondary,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        InviteCodeInput(
            value = state.inviteCode.filter(Char::isDigit).take(8),
            onValueChange = onInviteCodeChange,
        )

        SharedLedgerButton(
            text = "查找活动",
            onClick = {
                onValidateInviteCode(state.inviteCode.filter(Char::isDigit).take(8))
            },
            enabled = state.status != JoinActivityStatus.Loading,
            loading = state.status == JoinActivityStatus.Loading,
            loadingText = "正在查找",
            icon = Icons.Rounded.Search,
        )

        when (state.status) {
            JoinActivityStatus.InvalidCode -> JoinActivityMessage(
                icon = Icons.Rounded.Error,
                text = "邀请码无效，请检查后重试",
                containerColor = MaterialTheme.colorScheme.errorContainer,
                contentColor = MaterialTheme.colorScheme.onErrorContainer,
            )
            JoinActivityStatus.Deleted -> JoinActivityMessage(
                icon = Icons.Rounded.Error,
                text = "该活动已被删除",
                containerColor = MaterialTheme.colorScheme.errorContainer,
                contentColor = MaterialTheme.colorScheme.onErrorContainer,
            )
            JoinActivityStatus.AlreadyJoined -> JoinActivityMessage(
                icon = Icons.Rounded.Info,
                text = "你已加入此活动",
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            else -> Unit
        }
    }
}

@Composable
private fun InviteCodeInput(
    value: String,
    onValueChange: (String) -> Unit,
) {
    val focusRequesters = remember { List(8) { FocusRequester() } }
    var focusedIndex by rememberSaveable { mutableStateOf<Int?>(null) }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(8) { index ->
            if (index == 4) {
                Spacer(modifier = Modifier.width(SharedLedgerSpacing.Small))
            }
            val digit = value.getOrNull(index)?.toString() ?: ""
            val isFocused = focusedIndex == index
            Box(
                modifier = Modifier
                    .weight(1f)
                    .aspectRatio(3f / 4f)
                    .background(AppSurfaceLow, SharedLedgerRadius.Medium)
                    .then(
                        Modifier
                            .borderForInviteCode(
                                color = if (isFocused) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
                                width = if (isFocused) 2.dp else 1.dp,
                            )
                    ),
                contentAlignment = Alignment.Center,
            ) {
                BasicTextField(
                    value = digit,
                    onValueChange = { newValue ->
                        val nextDigit = newValue.filter(Char::isDigit).firstOrNull()
                        if (nextDigit != null) {
                            val nextCode = replaceDigitAt(value, index, nextDigit)
                            onValueChange(nextCode)
                            if (index < 7) {
                                focusedIndex = index + 1
                                focusRequesters[index + 1].requestFocus()
                            }
                        } else if (digit.isNotEmpty()) {
                            onValueChange(value.removeRange(index, index + 1))
                            if (index > 0) {
                                focusedIndex = index - 1
                                focusRequesters[index - 1].requestFocus()
                            }
                        }
                    },
                    modifier = Modifier
                        .fillMaxSize()
                        .focusRequester(focusRequesters[index])
                        .onFocusChanged { if (it.isFocused) focusedIndex = index }
                        .semantics {
                            contentDescription = "邀请码第 ${index + 1} 位"
                        },
                    textStyle = TextStyle(
                        fontFamily = SharedLedgerTextStyles.PageTitle.fontFamily,
                        fontSize = SharedLedgerTextStyles.PageTitle.fontSize,
                        lineHeight = SharedLedgerTextStyles.PageTitle.lineHeight,
                        fontWeight = SharedLedgerTextStyles.PageTitle.fontWeight,
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    ),
                    singleLine = true,
                    cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number,
                        imeAction = if (index == 7) ImeAction.Done else ImeAction.Next,
                    ),
                    decorationBox = { innerTextField ->
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (digit.isEmpty()) {
                                Text(
                                    text = "-",
                                    style = SharedLedgerTextStyles.PageTitle,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            innerTextField()
                        }
                    },
                )
            }
        }
    }
}

private fun replaceDigitAt(value: String, index: Int, digit: Char): String {
    val digits = value.toMutableList()
    if (index < digits.size) {
        digits[index] = digit
    } else {
        digits.add(digit)
    }
    return digits.joinToString("").filter(Char::isDigit).take(8)
}

private fun Modifier.borderForInviteCode(color: Color, width: androidx.compose.ui.unit.Dp): Modifier =
    this
        .background(
            color = Color.Transparent,
            shape = SharedLedgerRadius.Medium,
        )
        .border(
            width = width,
            color = color,
            shape = SharedLedgerRadius.Medium,
        )

@Composable
private fun JoinActivityMessage(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    text: String,
    containerColor: Color,
    contentColor: Color,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.Medium,
        color = containerColor,
        contentColor = contentColor,
    ) {
        Row(
            modifier = Modifier.padding(SharedLedgerSpacing.MediumSmall),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(20.dp))
            Text(text = text, style = SharedLedgerTextStyles.BodySecondary)
        }
    }
}

@Composable
private fun JoinActivityConfirmation(
    state: JoinActivityUiState,
    onParticipantSelected: (String) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XLarge),
    ) {
        ActivityPreviewCard(preview = state.preview)

        Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = SharedLedgerSpacing.XSmall),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "请选择你在账本中的身份",
                    style = SharedLedgerTextStyles.CardTitle,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "${state.preview.claimedCount}/${state.preview.participantCount} 已认领",
                    style = SharedLedgerTextStyles.Label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
                state.preview.participants.forEach { participant ->
                    ParticipantIdentityRow(
                        participant = participant,
                        selected = state.selectedParticipantId == participant.participantId ||
                            (state.selectedParticipantId == null && state.selectedParticipantName == participant.name),
                        onClick = { onParticipantSelected(participant.participantId) },
                    )
                }
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = SharedLedgerSpacing.XSmall),
                    shape = RoundedCornerShape(20.dp),
                    color = AppSurfaceLow,
                    border = BorderStroke(
                        1.dp,
                        MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f),
                    ),
                ) {
                    Text(
                        text = "参与人名单已锁定，只能认领已有参与人",
                        modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                        style = SharedLedgerTextStyles.BodySecondary,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun ActivityPreviewCard(preview: JoinActivityPreview) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = SharedLedgerRadius.ExtraLarge,
        color = AppSurfaceLow,
        border = BorderStroke(
            1.dp,
            MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f),
        ),
        shadowElevation = SharedLedgerElevation.Card,
    ) {
        Box(modifier = Modifier.fillMaxWidth()) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .offset(x = 40.dp, y = (-40).dp)
                    .size(128.dp)
                    .background(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f),
                                Color.Transparent,
                            ),
                        ),
                        shape = CircleShape,
                    ),
            )
            Row(
                modifier = Modifier.padding(SharedLedgerSpacing.Large),
                horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
                verticalAlignment = Alignment.Top,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                ) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ActivityChip(text = preview.kindLabel, tertiary = true)
                        ActivityChip(
                            text = "${preview.participantCount} 人参与",
                            icon = Icons.Rounded.Group,
                        )
                    }
                    Text(
                        text = preview.name,
                        modifier = Modifier.padding(top = SharedLedgerSpacing.XSmall),
                        style = SharedLedgerTextStyles.PageTitle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.CalendarMonth,
                            contentDescription = "活动日期",
                            modifier = Modifier.size(16.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = preview.dateRange,
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Surface(
                    modifier = Modifier.size(48.dp),
                    shape = RoundedCornerShape(16.dp),
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Rounded.FlightTakeoff,
                            contentDescription = "大型活动",
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ActivityChip(
    text: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    tertiary: Boolean = false,
) {
    Surface(
        shape = CircleShape,
        color = if (tertiary) MaterialTheme.colorScheme.tertiaryContainer
        else AppSurfaceVariant,
        contentColor = if (tertiary) MaterialTheme.colorScheme.onTertiaryContainer
        else MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Row(
            modifier = Modifier.padding(
                horizontal = SharedLedgerSpacing.Small,
                vertical = 2.dp,
            ),
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(12.dp))
            }
            Text(text = text, style = SharedLedgerTextStyles.Label)
        }
    }
}

@Composable
private fun ParticipantIdentityRow(
    participant: JoinActivityParticipant,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val isAvailable = participant.state == JoinParticipantState.Available
    val isCurrentUser = participant.state == JoinParticipantState.ClaimedByCurrentUser
    val rowColor = when {
        isCurrentUser -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.1f)
        isAvailable -> MaterialTheme.colorScheme.surface
        else -> AppSurfaceLow.copy(alpha = 0.5f)
    }
    val borderColor = when {
        isCurrentUser -> MaterialTheme.colorScheme.primary.copy(alpha = 0.2f)
        isAvailable -> MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)
        else -> MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.1f)
    }
    val rowModifier = Modifier
        .fillMaxWidth()
        .then(if (!isAvailable) Modifier else Modifier.selectable(
            selected = selected,
            enabled = true,
            role = Role.RadioButton,
            onClick = onClick,
        ))
        .semantics {
            contentDescription = when {
                isCurrentUser -> "我（${participant.name}），已认领"
                isAvailable -> "选择身份：${participant.name}"
                else -> "${participant.name}，已被认领"
            }
            if (isAvailable) {
                role = Role.RadioButton
                stateDescription = if (selected) "已选择" else "未选择"
            }
        }

    Surface(
        modifier = rowModifier,
        shape = RoundedCornerShape(20.dp),
        color = rowColor,
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = BorderStroke(1.dp, borderColor),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SharedLedgerSpacing.Medium),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Medium),
        ) {
            com.ffocalors.sharedledger.ui.components.ParticipantAvatar(
                name = participant.name,
                image = if (participant.participantId == "demo-participant-wangwu") {
                    painterResource(R.drawable.join_participant_avatar)
                } else {
                    null
                },
                modifier = Modifier.size(40.dp),
                backgroundColor = if (isCurrentUser) MaterialTheme.colorScheme.primaryContainer
                else MaterialTheme.colorScheme.surfaceVariant,
            )
            Text(
                text = if (isCurrentUser) "我 (${participant.name})" else participant.name,
                modifier = Modifier.weight(1f),
                style = SharedLedgerTextStyles.Body,
                color = if (isAvailable || isCurrentUser) MaterialTheme.colorScheme.onSurface
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            when {
                isCurrentUser -> ParticipantStatus(
                    icon = Icons.Rounded.CheckCircle,
                    text = "已认领",
                    color = MaterialTheme.colorScheme.primary,
                )
                !isAvailable -> ParticipantStatus(
                    icon = Icons.Rounded.Lock,
                    text = "已被认领",
                    color = MaterialTheme.colorScheme.outline,
                )
                else -> Surface(
                    shape = CircleShape,
                    color = if (selected) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.primaryContainer,
                    contentColor = if (selected) MaterialTheme.colorScheme.onPrimary
                    else MaterialTheme.colorScheme.onPrimaryContainer,
                ) {
                    Text(
                        text = if (selected) "已选择" else "这是我",
                        modifier = Modifier.padding(
                            horizontal = SharedLedgerSpacing.Medium,
                            vertical = SharedLedgerSpacing.XSmall,
                        ),
                        style = SharedLedgerTextStyles.Label,
                    )
                }
            }
        }
    }
}

@Composable
private fun ParticipantStatus(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    text: String,
    color: Color,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.XSmall),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(18.dp), tint = color)
        Text(text = text, style = SharedLedgerTextStyles.Label, color = color)
    }
}

@Composable
private fun JoinActivityBottomBar(
    state: JoinActivityUiState,
    onJoinActivity: (String) -> Unit,
) {
    val currentUserParticipant = state.preview.participants.firstOrNull {
        it.state == JoinParticipantState.ClaimedByCurrentUser
    }
    val identityId = state.selectedParticipantId ?: currentUserParticipant?.participantId
    val canJoin = identityId != null && identityId.isNotBlank() && state.status == JoinActivityStatus.ReadyToJoin

    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            modifier = Modifier
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxWidth()
                .navigationBarsPadding(),
            shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
            color = ActivityBottomBarColor,
            shadowElevation = SharedLedgerElevation.Floating,
        ) {
            SharedLedgerButton(
                text = when (state.status) {
                    JoinActivityStatus.Joined -> "已加入"
                    else -> "确认加入"
                },
                onClick = { identityId?.let(onJoinActivity) },
                enabled = canJoin,
                variant = if (state.status == JoinActivityStatus.Joined) {
                    SharedLedgerButtonVariant.Success
                } else {
                    SharedLedgerButtonVariant.Primary
                },
                loading = state.status == JoinActivityStatus.Joining,
                loadingText = "正在加入",
                icon = if (state.status == JoinActivityStatus.Joined) Icons.Rounded.CheckCircle else Icons.Rounded.ArrowForward,
                modifier = Modifier.padding(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = SharedLedgerSpacing.Large,
                ),
            )
        }
    }
}

@Preview(name = "加入活动 - 输入邀请码", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun JoinActivityScreenInputPreview() {
    SharedLedgerTheme {
        JoinActivityScreen()
    }
}

@Preview(name = "加入活动 - 活动预览", showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun JoinActivityScreenReadyPreview() {
    SharedLedgerTheme {
        JoinActivityScreen(
            state = JoinActivityUiState(
                inviteCode = "12345678",
                status = JoinActivityStatus.ReadyToJoin,
            ),
        )
    }
}
