package com.qhkt.message.controller;


import com.qhkt.common.domain.dto.PageDTO;
import com.qhkt.message.domain.dto.SmsThirdPlatformDTO;
import com.qhkt.message.domain.dto.SmsThirdPlatformFormDTO;
import com.qhkt.message.domain.query.SmsThirdPlatformPageQuery;
import com.qhkt.message.service.ISmsThirdPlatformService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * <p>
 * 第三方云通讯平台 前端控制器
 * </p>
 *
 * @author 虎哥
 * @since 2022-08-19
 */
@Api(tags = "短信平台管理接口")
@RestController
@RequestMapping("/sms-platforms")
@RequiredArgsConstructor
public class SmsThirdPlatformController {

    private final ISmsThirdPlatformService smsThirdPlatformService;

    @PostMapping
    @ApiOperation("新增短信平台信息")
    public Long saveSmsThirdPlatform(@RequestBody SmsThirdPlatformFormDTO smsThirdPlatformDTO){
        return smsThirdPlatformService.saveSmsThirdPlatform(smsThirdPlatformDTO);
    }

    @PutMapping("/{id}")
    @ApiOperation("更新短信平台信息")
    public void updateSmsThirdPlatform(
            @RequestBody SmsThirdPlatformFormDTO smsThirdPlatformDTO,
            @ApiParam(value = "短信平台id", example = "1") @PathVariable("id") Long id){
        smsThirdPlatformDTO.setId(id);
        smsThirdPlatformService.updateSmsThirdPlatform(smsThirdPlatformDTO);
    }

    @GetMapping
    @ApiOperation("分页查询短信平台信息")
    public PageDTO<SmsThirdPlatformDTO> querySmsThirdPlatforms(SmsThirdPlatformPageQuery pageQuery){
        return smsThirdPlatformService.querySmsThirdPlatforms(pageQuery);
    }

    @GetMapping("/{id}")
    @ApiOperation("根据id查询短信平台信息")
    public SmsThirdPlatformDTO querySmsThirdPlatform(
            @ApiParam(value = "短信平台id", example = "1") @PathVariable("id") Long id){
        return smsThirdPlatformService.querySmsThirdPlatform(id);
    }
}
