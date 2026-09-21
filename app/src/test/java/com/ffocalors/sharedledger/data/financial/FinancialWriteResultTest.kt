package com.ffocalors.sharedledger.data.financial

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class FinancialWriteResultTest {
    @Test
    fun committedRefreshFailureIsNotRetryableAsANewWrite() {
        val result = FinancialWriteResult.committedRefreshFailure<String>(
            operationId = "transfer-1",
            message = "资金操作已成功，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
        )

        assertFalse(result.isSuccess)
        assertTrue(result.isCommitted)
        assertTrue(result.requiresRefresh)
        assertEquals(FinancialWriteState.COMMITTED_REFRESH_FAILED, result.state)
        assertEquals("transfer-1", result.committedOperationId)
        assertEquals("资金操作已成功，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交", result.errorMessage)
        assertNull(result.value)
    }

    @Test
    fun validationFailureRemainsRetryableFailure() {
        val result = FinancialWriteResult.failure<String>("金额必须大于 0")

        assertFalse(result.isSuccess)
        assertFalse(result.isCommitted)
        assertFalse(result.requiresRefresh)
        assertEquals(FinancialWriteState.FAILED, result.state)
        assertNull(result.committedOperationId)
    }

    @Test
    fun repositoryMapsCommittedRefreshExceptionWithoutTurningItIntoRetryableFailure() {
        val result = mapFinancialWriteError<String>(
            FinancialWriteCommittedException(
                operationId = "transfer-2",
                userMessage = "资金操作已成功，但最新记录暂时无法刷新，请稍后刷新确认，勿重复提交",
            ),
        )

        assertEquals(FinancialWriteState.COMMITTED_REFRESH_FAILED, result.state)
        assertTrue(result.isCommitted)
        assertEquals("transfer-2", result.committedOperationId)
        assertFalse(result.isSuccess)
    }

    @Test
    fun unknownWriteIsDistinctFromBusinessFailureAndCommittedRefreshFailure() {
        val networkError = IOException("request timeout")
        val unknown = mapFinancialWriteError<String>(
            FinancialWriteUnknownException(null, "资金操作结果未知，请先查看或刷新资金记录，勿重复提交", networkError),
        )
        val businessFailure = mapFinancialWriteError<String>(FinancialOperationException("SQLSTATE 23514"))
        val committed = mapFinancialWriteError<String>(
            FinancialWriteCommittedException("transfer-3", "已提交但刷新失败"),
        )

        assertEquals(FinancialWriteState.UNKNOWN, unknown.state)
        assertTrue(unknown.isUnknown)
        assertFalse(unknown.isCommitted)
        assertTrue(isFinancialNetworkFailure(networkError))
        assertFalse(isFinancialNetworkFailure(FinancialOperationException("SQLSTATE 23514")))
        assertEquals(FinancialWriteState.FAILED, businessFailure.state)
        assertFalse(businessFailure.isUnknown)
        assertFalse(businessFailure.isCommitted)
        assertEquals(FinancialWriteState.COMMITTED_REFRESH_FAILED, committed.state)
        assertTrue(committed.isCommitted)
        assertFalse(committed.isUnknown)
    }

    @Test
    fun concurrentFinancialVersionConflictHasRecoveryMessage() {
        assertEquals(
            "当前资金方案已发生变化，请重新查看最新方案后重试。",
            FinancialErrorMapper.toUserMessage(RuntimeException("SQLSTATE 40001")),
        )
        assertEquals(
            "当前资金方案已发生变化，请重新查看最新方案后重试。",
            FinancialErrorMapper.toUserMessage(RuntimeException("code=40P01")),
        )
    }

    @Test
    fun financialConflictMessagesKeepCausesDistinct() {
        assertEquals(
            "预存余额不足，无法执行这笔返还，请刷新后查看最新状态。",
            FinancialErrorMapper.toUserMessage(RuntimeException("SQLSTATE 23514: prepayment return exceeds current available balance")),
        )
        assertEquals(
            "当前债务已被后续还款消耗，无法执行这笔资金操作，请刷新后查看最新状态。",
            FinancialErrorMapper.toUserMessage(RuntimeException("SQLSTATE 23514: transfer settlement component exceeds current bilateral debt")),
        )
        assertEquals(
            "最终结算路径已变化，无法执行，请重新查看方案并创建新的最终结算。",
            FinancialErrorMapper.toUserMessage(RuntimeException("SQLSTATE 23514: final settlement path no longer matches current plan")),
        )
    }
}
