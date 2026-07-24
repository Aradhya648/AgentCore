import { PageContainer } from "@/components/layout/PageContainer";
import { Compass } from "lucide-react";

export function ExplorePage() {
  return (
    <PageContainer width="canvas">
      <h1 className="text-xl font-semibold text-foreground">探索</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        发现并使用社区发布的 Agent、团队、模板与工具
      </p>

      {/* The public marketplace (user-published capabilities) needs the
          capability domain + market entities — a Day 2 build. 平台内置工具改在
          「工具箱」(/toolbox) 专属展示，探索页只聚焦社区/公共能力，避免两个入口重复同一份清单。 */}
      <section className="mt-6">
        <h2 className="text-base font-medium text-foreground">公共市场</h2>
        <div className="mt-3 flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-16 text-center">
          <Compass size={28} className="text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">
            公共 Agent / 团队 / 模板 / 工具即将上线
          </p>
          <p className="text-xs text-muted-foreground/70">
            用户发布的公共能力将在此以网格形式展示（Day 2）
          </p>
        </div>
      </section>
    </PageContainer>
  );
}
