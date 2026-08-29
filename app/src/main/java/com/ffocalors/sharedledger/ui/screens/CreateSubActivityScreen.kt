package com.ffocalors.sharedledger.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
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
import androidx.compose.ui.tooling.preview.Preview
import com.ffocalors.sharedledger.ui.components.ParticipantAvatar
import com.ffocalors.sharedledger.ui.components.ParticipantUiModel
import com.ffocalors.sharedledger.ui.components.SharedLedgerPrimaryButton
import com.ffocalors.sharedledger.ui.components.SharedLedgerTextField
import com.ffocalors.sharedledger.ui.components.SharedLedgerTopBar
import com.ffocalors.sharedledger.ui.demo.DemoData
import com.ffocalors.sharedledger.ui.theme.SharedLedgerDimens
import com.ffocalors.sharedledger.ui.theme.SharedLedgerRadius
import com.ffocalors.sharedledger.ui.theme.SharedLedgerSpacing
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTextStyles
import com.ffocalors.sharedledger.ui.theme.SharedLedgerTheme

/**
 * Static V0.1 form for creating a child activity. It only owns local form
 * state; the host decides what to do after the user taps create.
 */
@Composable
fun CreateSubActivityScreen(
    parentActivityName: String = "日本旅行",
    participants: List<ParticipantUiModel> = DemoData.japanTravel.participants,
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onCreate: () -> Unit = {},
) {
    var activityName by rememberSaveable { mutableStateOf("") }
    var selectedNamesCsv by rememberSaveable {
        mutableStateOf(participants.joinToString("|") { it.name })
    }
    val selectedNames = selectedNamesCsv.split("|").filter { it.isNotBlank() }.toSet()

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            SharedLedgerTopBar(
                title = "创建子活动",
                showBackButton = true,
                onBackClick = onBack,
                containerColor = MaterialTheme.colorScheme.background,
            )
        },
        bottomBar = {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .imePadding()
                    .padding(
                        horizontal = SharedLedgerSpacing.Large,
                        vertical = SharedLedgerSpacing.Medium,
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                SharedLedgerPrimaryButton(
                    text = "创建子活动",
                    onClick = onCreate,
                    modifier = Modifier.widthIn(max = SharedLedgerDimens.ContentMaxWidth),
                )
            }
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .widthIn(max = SharedLedgerDimens.ContentMaxWidth)
                .fillMaxSize()
                .padding(
                    start = SharedLedgerSpacing.Large,
                    top = innerPadding.calculateTopPadding() + SharedLedgerSpacing.Medium,
                    end = SharedLedgerSpacing.Large,
                    bottom = innerPadding.calculateBottomPadding() + SharedLedgerSpacing.Large,
                )
                .verticalScroll(rememberScrollState())
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
                            text = parentActivityName,
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
                trailing = "已选择 ${selectedNames.size} 人",
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = SharedLedgerRadius.ExtraLarge,
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Column(modifier = Modifier.padding(SharedLedgerSpacing.Small)) {
                        participants.forEach { participant ->
                            val selected = participant.name in selectedNames
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        val nextNames = selectedNames.toMutableSet().apply {
                                            if (selected) remove(participant.name) else add(participant.name)
                                        }
                                        selectedNamesCsv = participants
                                            .map { it.name }
                                            .filter { it in nextNames }
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
                                    backgroundColor = participant.backgroundColor,
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
        }
    }
}

@Composable
private fun FormSection(
    title: String,
    trailing: String? = null,
    content: @Composable () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(SharedLedgerSpacing.Small)) {
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
        CreateSubActivityScreen()
    }
}
