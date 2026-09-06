package com.qhkt.promotion.strategy.scope;

import com.qhkt.api.dto.promotion.OrderCourseDTO;
import com.qhkt.promotion.constants.ScopeType;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

import java.util.List;

@Getter
@RequiredArgsConstructor
public class CategoryScope implements Scope {

    private final List<Long> scopeIds;

    @Override
    public boolean canUse(OrderCourseDTO course) {
        return scopeIds.contains(course.getCateId());
    }

    @Override
    public ScopeType getType() {
        return ScopeType.CATEGORY;
    }
}
