package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.RadioButtonUnchecked
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.ErrorBanner
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.SharedLedgerButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerCtaBottomBar
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.components.rememberSharedLedgerHazeState
import com.ffocalors.sharedledger.ui.components.sharedLedgerHazeSource
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.AvatarBackground
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme
import com.ffocalors.sharedledger.data.activity.ActivityDetail

data class CreateSubActivityParticipant(
    val id: String,
    val name: String,
    val avatarBackground: AvatarBackground,
)

/**
 * Form for creating a child activity. It owns local input state; the host
 * validates and persists the request after the user taps create.
 */
@Composable
fun CreateSubActivityScreen(
    parentActivityName: String = "",
    participants: List<CreateSubActivityParticipant> = emptyList(),
    activity: ActivityDetail? = null,
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onCreate: (String, List<String>) -> Unit = { _, _ -> },
    isLoading: Boolean = false,
    errorMessage: String? = null,
) {
    val displayParentActivityName = activity?.summary?.name ?: parentActivityName
    val displayParticipants = activity?.participants?.map { participant ->
        CreateSubActivityParticipant(
            id = participant.id,
            name = participant.name,
            avatarBackground =
            if (participant.claimedUserId != null) AvatarBackground.Bound(participant.avatarStyle, participant.claimedUserId)
            else AvatarBackground.Unbound(participant.id),
        )
    } ?: participants
    var activityName by rememberSaveable { mutableStateOf("") }
    var selectedIdsCsv by rememberSaveable(displayParticipants.joinToString("|") { it.id }) {
        mutableStateOf(displayParticipants.joinToString("|") { it.id })
    }
    val hazeState = rememberSharedLedgerHazeState()
    val selectedIds = selectedIdsCsv.split("|").filter { it.isNotBlank() }.toSet()

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "创建子活动",
                showBackButton = true,
                onBackClick = onBack,
                hazeState = hazeState,
                containerColor = MaterialTheme.colorScheme.background,
            )
        },
        bottomBar = {
            SharedLedgerCtaBottomBar(backgroundColor = MaterialTheme.colorScheme.background, hazeState = hazeState) {
                SharedLedgerButton(
                    text = "创建子活动",
                    onClick = { onCreate(activityName.trim(), displayParticipants.map { it.id }.filter { it in selectedIds }) },
                    enabled = activityName.isNotBlank() && selectedIds.isNotEmpty() && !isLoading,
                    loading = isLoading,
                    loadingText = "正在创建",
                )
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.TopCenter,
        ) {
        Column(
            modifier = Modifier
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxSize()
                .sharedLedgerHazeSource(hazeState)
                .verticalScroll(rememberScrollState())
                .padding(
                    start = SharedLedgerDimens.PageHorizontalPadding,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerDimens.PageHorizontalPadding,
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Medium,
                )
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Large),
        ) {
            FormSection(title = "所属活动") {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = SharedLedgerRadius.ExtraLarge,
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Row(
                        modifier = Modifier.padding(SharedLedgerSpacing.MediumLarge),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = displayParentActivityName,
                            style = SharedLedgerTextStyles.Body,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = "大型活动",
                            modifier = Modifier.padding(start = SharedLedgerSpacing.Small),
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            FormSection(title = "子活动名称") {
                SharedLedgerTextField(
                    value = activityName,
                    onValueChange = { activityName = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = "例如：早餐、门票或酒店",
                )
            }

            FormSection(
                title = "参与人",
                trailing = "已选择 ${selectedIds.size} 人",
            ) {                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = SharedLedgerRadius.ExtraLarge,
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Column(modifier = Modifier.padding(SharedLedgerSpacing.Small)) {
                        if (displayParticipants.isEmpty()) {
                            Text(
                                text = "当前没有可用于子活动的参与人",
                                modifier = Modifier.padding(SharedLedgerSpacing.Medium),
                                style = SharedLedgerTextStyles.BodySecondary,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                        displayParticipants.forEach { participant ->
                            val selected = participant.id in selectedIds
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(SharedLedgerRadius.Medium)
                                    .clickable {
                                        val nextIds = selectedIds.toMutableSet().apply {
                                            if (selected) remove(participant.id) else add(participant.id)
                                        }
                                        selectedIdsCsv = displayParticipants
                                            .map { it.id }
                                            .filter { it in nextIds }
                                            .joinToString("|")
                                    }
                                    .padding(
                                        horizontal = SharedLedgerSpacing.MediumSmall,
                                        vertical = SharedLedgerSpacing.Small,
                                    ),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                ParticipantAvatar(
                                    name = participant.name,
                                    background = participant.avatarBackground,
                                    size = SharedLedgerDimens.AvatarMedium,
                                )
                                Text(
                                    text = participant.name,
                                    modifier = Modifier
                                        .weight(1f)
                                        .padding(horizontal = SharedLedgerSpacing.Medium),
                                    style = SharedLedgerTextStyles.Body,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Icon(
                                    imageVector = if (selected) {
                                        Icons.Rounded.CheckCircle
                                    } else {
                                        Icons.Rounded.RadioButtonUnchecked
                                    },
                                    contentDescription = if (selected) "已选择" else "未选择",
                                    modifier = Modifier.size(SharedLedgerDimens.IconMedium),
                                    tint = if (selected) {
                                        MaterialTheme.colorScheme.primary
                                    } else {
                                        MaterialTheme.colorScheme.outline
                                    },
                                )
                            }
                        }
                    }
                }
            }

            FormSection(title = "基准币") {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = SharedLedgerRadius.ExtraLarge,
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Row(
                        modifier = Modifier.padding(SharedLedgerSpacing.MediumLarge),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "CNY",
                            style = SharedLedgerTextStyles.Body,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = "人民币",
                            modifier = Modifier.padding(start = SharedLedgerSpacing.Small),
                            style = SharedLedgerTextStyles.BodySecondary,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (errorMessage != null) {
                ErrorBanner(errorMessage)
            }
        }
        }
    }
}

@Composable
private fun FormSection(
    title: String,
    trailing: String? = null,
    content: @Composable () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.MediumSmall)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = title,
                style = SharedLedgerTextStyles.SectionTitle,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.weight(1f),
            )
            if (trailing != null) {
                Text(
                    text = trailing,
                    style = SharedLedgerTextStyles.BodySecondary,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        content()
    }
}

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun CreateSubActivityScreenPreview() {
    SharedLedgerTheme {
        CreateSubActivityScreen(
            parentActivityName = "日本旅行",
            participants = DemoData.japanTravel.participants.mapIndexed { index, participant ->
                CreateSubActivityParticipant("preview-$index", participant.name, participant.avatarBackground)
            },
        )
    }
}
