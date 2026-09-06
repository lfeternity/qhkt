package com.qhkt.promotion.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.common.domain.dto.PageDTO;
import com.qhkt.promotion.domain.dto.UserCouponDTO;
import com.qhkt.promotion.domain.po.UserCoupon;
import com.qhkt.promotion.domain.query.UserCouponQuery;
import com.qhkt.promotion.domain.vo.CouponVO;

import java.util.List;

/**
 * <p>
 * 用户领取优惠券的记录，是真正使用的优惠券信息 服务类
 * </p>
 *
 * @author 虎哥
 */
public interface IUserCouponService extends IService<UserCoupon> {
    void receiveCoupon(Long couponId);

    void checkAndCreateUserCoupon(UserCouponDTO uc);

    void exchangeCoupon(String code);

    PageDTO<CouponVO> queryMyCouponPage(UserCouponQuery query);

    void writeOffCoupon(List<Long> userCouponIds);

    void refundCoupon(List<Long> userCouponIds);

    List<String> queryDiscountRules(List<Long> userCouponIds);
}
