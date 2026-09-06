package com.qhkt.common.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import com.qhkt.common.constants.ErrorInfo;
import com.qhkt.common.exceptions.BadRequestException;
import lombok.Getter;

@Getter
public enum UserType implements BaseEnum{
    STAFF(1, "其他员工"),
    STUDENT(2, "学生"),
    TEACHER(3, "老师"),
    ;
    @EnumValue
    int value;
    String desc;

    UserType(int value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    public static UserType of(int value) {
        for (UserType type : UserType.values()) {
            if (type.getValue() == value) {
                return type;
            }
        }
        throw new BadRequestException(ErrorInfo.Msg.INVALID_USER_TYPE);
    }
}
