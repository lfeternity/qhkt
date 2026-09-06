package com.qhkt.promotion.strategy.scope;

import com.qhkt.api.client.course.CourseClient;
import com.qhkt.api.dto.course.CourseSimpleInfoDTO;
import com.qhkt.common.exceptions.BizIllegalException;
import com.qhkt.common.utils.CollUtils;
import com.qhkt.promotion.constants.ScopeType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.stream.Collectors;

@RequiredArgsConstructor
@Component(ScopeType.COURSE_HANDLER_NAME)
public class CourseScopeNameHandler implements ScopeNameHandler {

    private final CourseClient courseClient;

    @Override
    public List<String> getNameByIds(List<Long> scopeIds) {
        List<CourseSimpleInfoDTO> infos = courseClient.getSimpleInfoList(scopeIds);
        if (CollUtils.isEmpty(infos)) {
            throw new BizIllegalException("课程信息不存在");
        }
        return infos.stream().map(CourseSimpleInfoDTO::getName).collect(Collectors.toList());
    }
}
