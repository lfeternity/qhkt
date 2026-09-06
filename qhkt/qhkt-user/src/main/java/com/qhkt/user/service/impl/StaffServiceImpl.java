package com.qhkt.user.service.impl;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.qhkt.api.cache.RoleCache;
import com.qhkt.common.domain.dto.PageDTO;
import com.qhkt.common.enums.UserType;
import com.qhkt.common.utils.BeanUtils;
import com.qhkt.user.domain.po.UserDetail;
import com.qhkt.user.domain.query.UserPageQuery;
import com.qhkt.user.domain.vo.StaffVO;
import com.qhkt.user.service.IStaffService;
import com.qhkt.user.service.IUserDetailService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * <p>
 * 员工详情表 服务实现类
 * </p>
 *
 * @author 虎哥
 * @since 2022-07-12
 */
@Service
@RequiredArgsConstructor
public class StaffServiceImpl implements IStaffService {

    private final IUserDetailService detailService;
    private final RoleCache roleCache;
    @Override
    public PageDTO<StaffVO> queryStaffPage(UserPageQuery query) {
        // 1.搜索
        Page<UserDetail> p = detailService.queryUserDetailByPage(query, UserType.STAFF);
        // 2.处理vo
        return PageDTO.of(p, u -> {
            StaffVO v = BeanUtils.toBean(u, StaffVO.class);
            v.setRoleName(roleCache.getRoleName(u.getRoleId()));
            return v;
        });
    }
}
