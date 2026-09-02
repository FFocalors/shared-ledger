package com.ffocalors.sharedledger.ui.navigation

import com.ffocalors.sharedledger.ui.screens.ExpenseDetailStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class DemoExpenseActionTest {
    @Test
    fun expenseDemoActionsUpdateStatusAndGiveFeedback() {
        var status = ExpenseDetailStatus.Active
        var message = ""
        val handler = DemoExpenseActionHandler({ status = it }, { message = it })

        handler.void("expense-1")
        assertEquals(ExpenseDetailStatus.Deleted, status)
        assertEquals("演示：账单 expense-1 已作废，历史记录仍保留", message)
        handler.restore("expense-1")
        assertEquals(ExpenseDetailStatus.Active, status)
        handler.addRefund("expense-1")
        assertEquals("演示：已准备为账单 expense-1 添加退款", message)
    }
}
