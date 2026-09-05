package com.ffocalors.sharedledger.data.activity

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Test

class ActivityErrorMapperTest {
    @Test
    fun mapsContractErrorsToReadableMessages() {
        assertEquals("你没有权限执行此操作，或已不是活动成员", ActivityErrorMapper.toUserMessage(Exception("42501 permission denied")))
        assertEquals("活动不存在或已被删除", ActivityErrorMapper.toUserMessage(Exception("P0002 activity not found")))
        assertEquals("该参与人已被认领，或你已加入此活动", ActivityErrorMapper.toUserMessage(Exception("23505 claim conflict")))
        assertEquals("网络连接失败，请检查网络后重试", ActivityErrorMapper.toUserMessage(IOException("connection reset")))
    }

    @Test
    fun hidesUnknownBackendDetails() {
        assertEquals("操作失败，请稍后重试", ActivityErrorMapper.toUserMessage(Exception("postgresql password detail")))
    }
}
