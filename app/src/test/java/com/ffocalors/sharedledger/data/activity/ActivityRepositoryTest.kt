package com.ffocalors.sharedledger.data.activity

import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.serialization.json.Json

class ActivityRepositoryTest {
    @Test
    fun deleteConfirmationAcceptsMissingOrSoftDeletedRowButNotActiveRow() {
        assertTrue(isDeleteConfirmedByRows(emptyList()))
        assertTrue(isDeleteConfirmedByRows(listOf(activityRow(isDeleted = true))))
        assertFalse(isDeleteConfirmedByRows(listOf(activityRow(isDeleted = false))))
    }

    @Test
    fun detailReadRejectsSoftDeletedActivityAsNotFound() {
        val error = runCatching { requireVisibleActivity(activityRow(isDeleted = true)) }.exceptionOrNull()
        val active = activityRow(isDeleted = false)

        assertTrue(error is ActivityOperationException)
        assertTrue((error as? ActivityOperationException)?.kind == ActivityFailureKind.NotFound)
        assertTrue((error as? ActivityOperationException)?.userMessage == "活动不存在或已被删除")
        assertSame(active, requireVisibleActivity(active))
    }

    @Test
    fun ledgerUnitDtoKeepsSoftDeleteMetadata() {
        val row = Json.decodeFromString<LedgerUnitRowDto>(
            """{"id":"unit-1","activity_id":"activity-1","name":"门票","type":"sub_activity","is_deleted":true,"deleted_at":"2026-09-13T12:00:00Z","deleted_by":"user-2"}""",
        )

        assertTrue(row.isDeleted)
        assertTrue(row.deletedAt?.contains("2026-09-13") == true)
        assertTrue(row.deletedBy == "user-2")
    }

    private fun activityRow(isDeleted: Boolean) = ActivityRowDto(
        id = "activity-1",
        name = "Trip",
        type = "normal",
        joinCode = "12345678",
        baseCurrency = "CNY",
        multiCurrencyEnabled = false,
        createdBy = "user-1",
        isDeleted = isDeleted,
    )
}
