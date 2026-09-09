package com.ffocalors.sharedledger.ui.screens

import com.ffocalors.sharedledger.ui.demo.DemoRouteIds

internal fun demoExpenseDetailUiState(expenseId: String): ExpenseDetailUiState =
    ExpenseDetailUiState(
        expenseId = expenseId,
        title = "预览账单",
        status = if (expenseId == DemoRouteIds.DINNER_EXPENSE) ExpenseDetailStatus.Deleted else ExpenseDetailStatus.Active,
        splits = listOf(ExpenseSplitUiState("预览参与人", "100")),
    )
