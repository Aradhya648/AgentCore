import { CapabilityPackCard } from "@/components/tools/CapabilityPackCard";
import { CapabilityPage } from "@/components/tools/CapabilityPage";
import { GuidelineBlock } from "@/components/tools/GuidelineBlock";
import { SkillCard } from "@/components/tools/SkillCard";

/** 工具箱「能力」组 → AI 提示词：AI 遵循的提示词全文。常驻部分是系统提示词模板（全员
 * 共享准则 + CEO 完整提示词）；当前这批「技能」其实是几个内置工具的进阶用法（薄技能），
 * 不常驻、按需 consult 注入，故并入本页而非与工具并列——它们本质是 Prompt 注入、不是独立
 * 能力（决策见 UX §十二 / 术语表 三层模型）。部署上架的「能力包」在本页纯展示（包内技能
 * 已从薄技能区去重，避免与包卡片重复）。 */
export function GuidelinesPage() {
  return (
    <CapabilityPage
      title="AI 提示词"
      subtitle="AI 遵循的提示词全文：常驻的系统提示词模板（全员共享准则 + CEO 完整提示词），以及按需注入的工具进阶用法（薄技能）。每条 AI 回复还可查看「本回合实际提示词」。"
    >
      {(data) => {
        const packs = data.packs ?? [];
        const packSkillNames = new Set(
          packs.flatMap((pack) => pack.skills.map((s) => s.name)),
        );
        // Pack cards already list domain skills; keep the thin-skills strip for
        // platform mechanism skills only (delegate / debate / …).
        const thinSkills = data.skills.filter(
          (skill) => !packSkillNames.has(skill.name),
        );
        return (
          <div className="space-y-8">
            {packs.length > 0 && (
              <section data-testid="capability-packs">
                <h2 className="font-medium text-foreground text-sm">能力包</h2>
                <p className="mt-1 mb-3 text-muted-foreground text-xs">
                  本部署已上架的垂直领域能力；包内技能已对全体用户生效，按需注入对话。
                </p>
                <div className="space-y-3">
                  {packs.map((pack) => (
                    <CapabilityPackCard key={pack.id} pack={pack} />
                  ))}
                </div>
              </section>
            )}

            <section className="space-y-3">
              <GuidelineBlock
                title="全员共享准则"
                subtitle="每个 Agent（CEO 与队员）共享的基座：身份、表达风格、工具使用与安全。"
                text={data.guidelines.shared_base}
              />
              <GuidelineBlock
                title="CEO 专属提示词"
                subtitle="在全员共享准则之上，CEO 额外遵循的路由核心、能力目录与引用规范。"
                text={data.guidelines.ceo_addon}
              />
            </section>

            {thinSkills.length > 0 && (
              <section>
                <h2 className="font-medium text-foreground text-sm">
                  工具进阶用法（薄技能）
                </h2>
                <p className="mt-1 mb-3 text-muted-foreground text-xs">
                  这些不是独立能力，而是几个内置工具（delegate / debate / revise
                  / ask_user）的进阶
                  用法——把「怎么用好它」从常驻工具描述里拆出来、按需注入：CEO
                  的「能力目录」平时只挂 一行触发说明，要用时才 consult_skill
                  把完整指引拉回循环。等真正跨多工具的域级技能
                  （如合同审查）出现，再单独归类。
                </p>
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {thinSkills.map((skill) => (
                    <SkillCard key={skill.name} skill={skill} />
                  ))}
                </div>
              </section>
            )}
          </div>
        );
      }}
    </CapabilityPage>
  );
}
