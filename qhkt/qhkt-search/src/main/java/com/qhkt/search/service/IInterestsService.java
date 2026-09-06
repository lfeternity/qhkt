package com.qhkt.search.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.search.domain.po.Interests;
import com.qhkt.api.dto.course.CategoryBasicDTO;

import java.util.List;

/**
 * <p>
 * 用户兴趣表，保存感兴趣的二级分类id 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-07-21
 */
public interface IInterestsService extends IService<Interests> {

    void saveInterests(List<Long> interestedIds);

    List<CategoryBasicDTO> queryMyInterests();

    List<Long> queryMyInterestsIds();
}
