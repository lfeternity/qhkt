package com.qhkt.learning.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.api.dto.leanring.LearningLessonDTO;
import com.qhkt.learning.domain.dto.LearningRecordFormDTO;
import com.qhkt.learning.domain.po.LearningRecord;

/**
 * <p>
 * 学习记录表 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-12-10
 */
public interface ILearningRecordService extends IService<LearningRecord> {

    LearningLessonDTO queryLearningRecordByCourse(Long courseId);

    void addLearningRecord(LearningRecordFormDTO formDTO);
}
