package com.qhkt.trade.service;

import com.qhkt.trade.domain.dto.OrderDelayQueryDTO;
import com.qhkt.trade.domain.dto.PayApplyFormDTO;
import com.qhkt.trade.domain.vo.PayChannelVO;

import java.util.List;

public interface IPayService {
    List<PayChannelVO> queryPayChannels();

    String applyPayOrder(PayApplyFormDTO payApply);

    void queryPayResult(OrderDelayQueryDTO message);
}
