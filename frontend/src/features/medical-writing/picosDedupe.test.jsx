// 第10轮末修订（P1-50）：PICOS 重复行自动归并 + 422 人话化。
// 现场（r10-A w10-07）：入排规则重复行（双次填充叠加）触发服务端
// 『inclusion_modules must be unique』422——英文内部字段名直出、无重复行
// 标记、无定位，保存按钮重试4次全败，测试者靠网络监听才定位。
// 契约：
// 1) normalizePicosForWrite 保存前自动去重归并（保序、首现保留）——
//    重复行在写路径上消失，服务端唯一性校验不再被双击填充触发；
// 2) 服务端 _mw_journey_error_detail 对『<field> must be unique』映射
//    中文标签+可操作指引（防御层：任何绕过前端的调用也拿人话）。
import { describe, expect, it } from "vitest";

import {
  normalizePicosForWrite,
  PICOS_TEXT_LIST_FIELDS,
} from "./MedicalWritingAuthoringJourneySetup";

describe("PICOS 重复行自动归并（P1-50 前端去重）", () => {
  it("duplicate inclusion rows collapse keeping first occurrence order", () => {
    const picos = {
      inclusion_modules: [
        "诊断标准符合APA慢性咳嗽定义",
        "年龄18至75岁",
        "诊断标准符合APA慢性咳嗽定义",
        "不吸烟或戒烟≥12月",
        "年龄18至75岁",
      ],
      exclusion_modules: ["活动性感染", "活动性感染"],
      statistical_strategy: "MMRM主分析。",
    };
    const normalized = normalizePicosForWrite(picos);
    expect(normalized.inclusion_modules).toEqual([
      "诊断标准符合APA慢性咳嗽定义",
      "年龄18至75岁",
      "不吸烟或戒烟≥12月",
    ]);
    expect(normalized.exclusion_modules).toEqual(["活动性感染"]);
    expect(normalized.statistical_strategy).toBe("MMRM主分析。");
  });

  it("covers every picos list field and passes non-list scalars through", () => {
    const picos = Object.fromEntries([
      ...PICOS_TEXT_LIST_FIELDS.map((field) => [field, ["甲", "乙", "甲"]]),
      ["sample_size_strategy", "需63例/组。"],
      ["sample_size_anchor", ""],
    ]);
    const normalized = normalizePicosForWrite(picos);
    for (const field of PICOS_TEXT_LIST_FIELDS) {
      expect(normalized[field]).toEqual(["甲", "乙"]);
    }
    expect(normalized.sample_size_strategy).toBe("需63例/组。");
  });
});
