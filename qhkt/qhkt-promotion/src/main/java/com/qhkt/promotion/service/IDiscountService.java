package com.qhkt.promotion.service;

import com.qhkt.api.dto.promotion.CouponDiscountDTO;
import com.qhkt.api.dto.promotion.OrderCouponDTO;
import com.qhkt.api.dto.promotion.OrderCourseDTO;

import java.util.List;

public interface IDiscountService {
    List<CouponDiscountDTO> findDiscountSolution(List<OrderCourseDTO> orderCourses);

    CouponDiscountDTO queryDiscountDetailByOrder(OrderCouponDTO orderCouponDTO);
}
