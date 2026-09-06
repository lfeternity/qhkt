package com.qhkt.user.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.api.dto.user.LoginFormDTO;
import com.qhkt.api.dto.user.UserDTO;
import com.qhkt.common.domain.dto.LoginUserDTO;
import com.qhkt.user.domain.dto.UserFormDTO;
import com.qhkt.user.domain.po.User;
import com.qhkt.user.domain.vo.UserDetailVO;

/**
 * <p>
 * 学员用户表 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-06-28
 */
public interface IUserService extends IService<User> {
    LoginUserDTO queryUserDetail(LoginFormDTO loginDTO, boolean isStaff);

    void resetPassword(Long userId);

    UserDetailVO myInfo();

    void addUserByPhone(User user, String code);

    void updatePasswordByPhone(String cellPhone, String code, String password);

    Long saveUser(UserDTO userDTO);

    void updateUser(UserDTO userDTO);

    void updateUserWithPassword(UserFormDTO userDTO);

    /**
     * Verify the current user's password without exposing the password hash.
     */
    boolean checkPassword(String password);
}
