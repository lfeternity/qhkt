package com.qhkt.pay.service;

import com.qhkt.pay.sdk.dto.PayChannelDTO;
import com.qhkt.pay.domain.po.PayChannel;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 * <p>
 * 支付渠道 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-08-26
 */
public interface IPayChannelService extends IService<PayChannel> {

    Long addPayChannel(PayChannelDTO channelDTO);

    void updatePayChannel(PayChannelDTO channelDTO);
}
