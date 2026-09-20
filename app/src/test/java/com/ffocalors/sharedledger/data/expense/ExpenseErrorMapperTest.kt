package com.ffocalors.sharedledger.data.expense

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.math.BigDecimal

class ExpenseErrorMapperTest {
    @Test
    fun mapsSqlStatesToSafeUserMessages() {
        assertEquals("登录状态已失效，请重新登录", ExpenseErrorMapper.toUserMessage(RuntimeException("{\"code\":\"28000\"}")))
        assertEquals("你没有权限执行此操作，或已不是活动成员", ExpenseErrorMapper.toUserMessage(RuntimeException("code=42501")))
        assertEquals("账单不存在或已被删除", ExpenseErrorMapper.toUserMessage(RuntimeException("SQLSTATE P0002")))
        assertEquals("输入内容不符合账单规则", ExpenseErrorMapper.toUserMessage(RuntimeException("code: 23514")))
        assertEquals("账单与参与人信息发生冲突，请刷新后重试", ExpenseErrorMapper.toUserMessage(RuntimeException("code=23505")))
        assertEquals("当前活动状态不允许此操作", ExpenseErrorMapper.toUserMessage(RuntimeException("code=55000")))
        assertEquals("数据刚刚发生变化，请刷新后重试", ExpenseErrorMapper.toUserMessage(RuntimeException("code=40001")))
        assertEquals(
            "账单已发生结算，不能修改或删除其财务字段",
            ExpenseErrorMapper.toUserMessage(RuntimeException("code=23514: expense is settled")),
        )
    }

    @Test
    fun onlyTransportExceptionsBecomeNetworkMessage() {
        assertEquals("网络连接失败，请检查网络后重试", ExpenseErrorMapper.toUserMessage(IOException("transport failed")))
        assertEquals("操作失败，请稍后重试", ExpenseErrorMapper.toUserMessage(IllegalArgumentException("participant connection is invalid")))
    }

    @Test
    fun operationExceptionKeepsSanitizedMessage() {
        assertEquals(
            "输入内容不符合账单规则",
            ExpenseErrorMapper.toUserMessage(ExpenseOperationException("输入内容不符合账单规则", RuntimeException("secret SQL"))),
        )
    }

    @Test
    fun writeOutcomeSeparatesTransportUnknownFromBusinessFailureAndCommittedRefreshFailure() {
        val unknown = Result.failure<ExpenseMutationResult>(
            ExpenseOperationException("网络连接失败", IOException("request timeout")),
        ).toExpenseWriteResult()
        val failed = Result.failure<ExpenseMutationResult>(RuntimeException("code=40001")).toExpenseWriteResult()
        val committed = ExpenseWriteResult.committedRefreshFailure<ExpenseMutationResult>(
            operationId = "expense-1",
            message = "账单已保存，但最新详情暂时无法刷新，请稍后刷新确认，勿重复提交",
            value = ExpenseMutationResult("expense-1", BigDecimal.TEN, 2),
        )

        assertEquals(ExpenseWriteState.UNKNOWN, unknown.state)
        assertTrue(unknown.isUnknown)
        assertEquals(ExpenseWriteState.FAILED, failed.state)
        assertFalse(failed.isUnknown)
        assertEquals(ExpenseWriteState.COMMITTED_REFRESH_FAILED, committed.state)
        assertTrue(committed.isCommitted)
        assertEquals("expense-1", committed.operationId)
    }
}
