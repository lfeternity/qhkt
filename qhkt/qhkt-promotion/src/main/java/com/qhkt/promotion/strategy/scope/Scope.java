package com.qhkt.promotion.strategy.scope;

import com.qhkt.api.dto.promotion.OrderCourseDTO;
import com.qhkt.promotion.constants.ScopeType;

import java.util.List;

public interface Scope {

    boolean canUse(OrderCourseDTO course);

    ScopeType getType();

    List<Long> getScopeIds();
}
