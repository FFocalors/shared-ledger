# SharedLedger 前端文档

本目录记录 Android Jetpack Compose 前端的设计现状、优化边界和验收要求。

## 当前交接

- [Kimi Code 前端优化交接](./KIMICODE_FRONTEND_OPTIMIZATION_HANDOFF.md)

## 参考资料

- 设计稿与导出页面：[`../stitch/9598285378004174921/`](../stitch/9598285378004174921/)
- 后端业务基线：[`../backend/BUSINESS_LOGIC.md`](../backend/BUSINESS_LOGIC.md)
- 双账号 E2E 验收边界：[`../backend/E2E_ACCEPTANCE_CHECKLIST.md`](../backend/E2E_ACCEPTANCE_CHECKLIST.md)

## 文档使用原则

1. 前端优化不得改变业务含义、金额计算、身份绑定、权限、缓存、Realtime、附件或 Supabase RPC 契约。
2. Stitch 资料是视觉参考，不是可以覆盖真实业务状态的静态实现；运行时数据必须继续来自 ViewModel/Repository。
3. Preview 中可以使用示例数据，生产导航链不得接入 `DemoData`。
4. 验证结果需要区分静态 Preview、Kotlin 编译、单元测试和真机验收，不能互相替代。

