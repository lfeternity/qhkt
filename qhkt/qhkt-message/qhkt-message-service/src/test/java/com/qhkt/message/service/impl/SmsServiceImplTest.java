package com.qhkt.message.service.impl;

import com.qhkt.api.dto.sms.SmsInfoDTO;
import com.qhkt.message.domain.enums.SmsTemplate;
import com.qhkt.message.domain.po.MessageTemplate;
import com.qhkt.message.domain.po.NoticeTemplate;
import com.qhkt.message.domain.po.SmsThirdPlatform;
import com.qhkt.message.service.IMessageTemplateService;
import com.qhkt.message.service.INoticeTemplateService;
import com.qhkt.message.service.ISmsThirdPlatformService;
import com.qhkt.message.thirdparty.ISmsHandler;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SmsServiceImplTest {

    @Test
    void shouldTrySmsPlatformsInPriorityOrderUntilOneSucceeds() {
        ISmsThirdPlatformService platformService = mock(ISmsThirdPlatformService.class);
        INoticeTemplateService noticeTemplateService = mock(INoticeTemplateService.class);
        IMessageTemplateService messageTemplateService = mock(IMessageTemplateService.class);
        ISmsHandler primaryHandler = mock(ISmsHandler.class);
        ISmsHandler fallbackHandler = mock(ISmsHandler.class);
        SmsServiceImpl smsService = new SmsServiceImpl(
                Runnable::run, platformService, noticeTemplateService, messageTemplateService);
        ReflectionTestUtils.setField(smsService, "smsHandlers", Map.of(
                "primary", primaryHandler,
                "fallback", fallbackHandler));

        SmsInfoDTO smsInfo = new SmsInfoDTO();
        smsInfo.setTemplateCode(SmsTemplate.VERIFY_CODE.name());
        NoticeTemplate noticeTemplate = new NoticeTemplate().setId(1L).setIsSmsTemplate(true);
        MessageTemplate primaryTemplate = new MessageTemplate().setPlatformCode("primary");
        MessageTemplate fallbackTemplate = new MessageTemplate().setPlatformCode("fallback");
        when(noticeTemplateService.queryByCode(SmsTemplate.VERIFY_CODE.name()))
                .thenReturn(noticeTemplate);
        when(messageTemplateService.queryByNoticeTemplateId(1L))
                .thenReturn(List.of(fallbackTemplate, primaryTemplate));
        when(platformService.queryAllPlatform()).thenReturn(List.of(
                new SmsThirdPlatform().setCode("primary").setPriority(0),
                new SmsThirdPlatform().setCode("fallback").setPriority(1)));
        doThrow(new IllegalStateException("primary platform unavailable"))
                .when(primaryHandler).send(smsInfo, primaryTemplate);

        smsService.sendMessage(smsInfo);

        InOrder inOrder = inOrder(primaryHandler, fallbackHandler);
        inOrder.verify(primaryHandler).send(smsInfo, primaryTemplate);
        inOrder.verify(fallbackHandler).send(smsInfo, fallbackTemplate);
    }
}
