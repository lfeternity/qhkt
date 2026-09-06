package com.qhkt.learning.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.learning.domain.po.PointsRecord;
import com.qhkt.learning.domain.vo.PointsStatisticsVO;
import com.qhkt.learning.enums.PointsRecordType;

import java.util.List;

/**
 * <p>
 * 学习积分记录，每个月底清零 服务类
 * </p>
 *
 * @author 虎哥
 */
public interface IPointsRecordService extends IService<PointsRecord> {
    void addPointsRecord(Long userId, int points, PointsRecordType type);

    List<PointsStatisticsVO> queryMyPointsToday();

}
