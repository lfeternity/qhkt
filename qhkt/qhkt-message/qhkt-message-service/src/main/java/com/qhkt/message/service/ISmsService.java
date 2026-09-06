package com.qhkt.message.service;

import com.qhkt.api.dto.sms.SmsInfoDTO;
import com.qhkt.api.dto.user.UserDTO;
import com.qhkt.message.domain.po.NoticeTemplate;

import java.util.List;

public interface ISmsService {
    void sendMessageByTemplate(NoticeTemplate noticeTemplate, List<UserDTO> users);

    void sendMessage(SmsInfoDTO smsInfoDTO);

    void sendMessageAsync(SmsInfoDTO smsInfoDTO);
}
