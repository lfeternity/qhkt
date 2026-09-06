package com.qhkt.message.service;

import com.qhkt.message.domain.dto.MessageTemplateDTO;
import com.qhkt.message.domain.dto.MessageTemplateFormDTO;
import com.qhkt.message.domain.query.MessageTemplatePageQuery;
import com.qhkt.common.domain.dto.PageDTO;
import com.qhkt.message.domain.po.MessageTemplate;
import com.baomidou.mybatisplus.extension.service.IService;

import java.util.List;

/**
 * <p>
 * 第三方短信平台签名和模板信息 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-08-19
 */
public interface IMessageTemplateService extends IService<MessageTemplate> {

    List<MessageTemplate> queryByNoticeTemplateId(Long id);

    Long saveMessageTemplate(MessageTemplateFormDTO messageTemplateDTO);

    void updateMessageTemplate(MessageTemplateFormDTO messageTemplateDTO);

    PageDTO<MessageTemplateDTO> queryMessageTemplates(MessageTemplatePageQuery pageQuery);

    MessageTemplateDTO queryMessageTemplate(Long id);
}
