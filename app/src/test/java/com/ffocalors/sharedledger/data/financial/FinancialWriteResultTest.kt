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

    @Test
    fun finalSettlementActorPermissionExplainsWhoMayRecordPayment() {
        assertEquals(
            "仅这笔转账的付款方或收款方可以记录已转账",
            FinancialErrorMapper.toUserMessage(
                RuntimeException("SQLSTATE 42501: member must use claimed participant"),
            ),
        )
        assertEquals(
            "你不是这笔转账的一方；请选择未绑定参与人代记后重试",
            FinancialErrorMapper.toUserMessage(
                RuntimeException("SQLSTATE 42501: creator must be party or act on behalf"),
            ),
        )
        assertEquals(
            "创建者只能为这笔转账中尚未绑定账号的参与人代记",
            FinancialErrorMapper.toUserMessage(
                RuntimeException("SQLSTATE 42501: creator may act only for an unclaimed participant"),
            ),
        )
    }

    @Test
    fun finalSettlementErrorMappingDistinguishesContractModeAndStalePlan() {
        assertEquals(
            FINAL_SETTLEMENT_CONTRACT_UNAVAILABLE_MESSAGE,
            FinancialErrorMapper.toFinalSettlementUserMessage(
                RuntimeException("code=PGRST202: execute_final_settlement_v2 is not in the schema cache"),
            ),
        )
        assertEquals(
            "当前服务端不支持所选结算模式，请更新服务端后重试。",
            FinancialErrorMapper.toFinalSettlementUserMessage(
                RuntimeException("SQLSTATE 22023: settlement_mode check constraint failed"),
            ),
        )
        assertEquals(
            "当前结算方案已发生变化，请重新查看最新方案后重试。",
            FinancialErrorMapper.toFinalSettlementUserMessage(
                RuntimeException("SQLSTATE 40001: financial_version mismatch; refresh the plan"),
            ),
        )
        assertEquals(
            "最终结算请求缺少服务端要求的 request_id，请更新客户端后重试。",
            FinancialErrorMapper.toFinalSettlementUserMessage(
                RuntimeException("SQLSTATE 22023: expected_financial_version and request_id are required"),
            ),
        )
    }
}
