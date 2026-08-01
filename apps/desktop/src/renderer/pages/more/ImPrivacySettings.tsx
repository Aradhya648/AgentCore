import { BlockedUsersDialog } from "@/components/messages/BlockedUsersDialog";
import { Card } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  type DirectorySettings,
  type WhoCanFriend,
  getDirectory,
  normalizeWhoCanDm,
  updateDirectory,
} from "@/services/messaging";
import { Check, ChevronRight, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

interface OptionRow<T extends string> {
  value: T;
  label: string;
  description: string;
}

const DM_OPTIONS: OptionRow<"anyone" | "friends">[] = [
  {
    value: "anyone",
    label: "任何人",
    description: "可被搜到的用户均可向你发起私信（陌生人首条会进入消息请求）。",
  },
  {
    value: "friends",
    label: "仅好友",
    description: "只有已同意的好友可以向你发起新私信。",
  },
];

const FRIEND_OPTIONS: OptionRow<WhoCanFriend>[] = [
  {
    value: "anyone",
    label: "任何人",
    description: "可被搜到的用户均可向你发送好友申请。",
  },
  {
    value: "group_members",
    label: "仅共同群成员",
    description: "须与你有共同群聊的用户才能申请加好友。",
  },
  {
    value: "nobody",
    label: "不允许任何人",
    description: "关闭好友申请入口（已有好友不受影响）。",
  },
];

/**
 * 消息隐私设置（/more/messages）— discoverable + who_can_friend + who_can_dm
 * + 拉黑列表入口（消息IM.md §九）。
 */
export function ImPrivacySettings() {
  const [settings, setSettings] = useState<DirectorySettings | null>(null);
  const [pending, setPending] = useState(false);
  const [blocksOpen, setBlocksOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    getDirectory()
      .then((d) => alive && setSettings(d))
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载消息隐私设置失败");
      });
    return () => {
      alive = false;
    };
  }, []);

  const patch = async (next: Partial<DirectorySettings>) => {
    if (!settings) return;
    setPending(true);
    const prev = settings;
    setSettings({ ...settings, ...next });
    try {
      const saved = await updateDirectory(next);
      setSettings(saved);
      notifySuccess("已保存");
    } catch (e) {
      setSettings(prev);
      notifyError(e, "保存失败");
    } finally {
      setPending(false);
    }
  };

  const whoCanDm = settings ? normalizeWhoCanDm(settings.who_can_dm) : null;
  const whoCanFriend: WhoCanFriend = settings?.who_can_friend ?? "anyone";

  return (
    <div>
      <SettingsHeader
        title="消息隐私"
        description="控制他人能否搜到你、谁可以加你为好友，以及谁可以向你发起私信。"
      />

      <section className="mt-6 space-y-6">
        <Card className="flex items-start justify-between gap-4 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-foreground">可被搜索</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              关闭后，他人无法通过用户名或 ID
              精确搜到你（已在群内的身份不受影响）。
            </p>
          </div>
          {settings === null ? (
            <Loader2
              size={16}
              className="mt-0.5 shrink-0 animate-spin text-muted-foreground/50"
            />
          ) : (
            <Switch
              checked={settings.discoverable}
              onCheckedChange={(discoverable) => void patch({ discoverable })}
              disabled={pending}
              label="可被搜索"
            />
          )}
        </Card>

        <div>
          <h2 className="text-sm font-medium text-foreground">
            谁可以加我为好友
          </h2>
          <div className="mt-3 space-y-2">
            {FRIEND_OPTIONS.map((option) => (
              <SelectOptionRow
                key={option.value}
                option={option}
                selected={whoCanFriend === option.value}
                disabled={settings === null || pending}
                onSelect={() => void patch({ who_can_friend: option.value })}
              />
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-medium text-foreground">谁可以私信我</h2>
          <div className="mt-3 space-y-2">
            {DM_OPTIONS.map((option) => (
              <SelectOptionRow
                key={option.value}
                option={option}
                selected={whoCanDm === option.value}
                disabled={settings === null || pending}
                onSelect={() => void patch({ who_can_dm: option.value })}
              />
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={() => setBlocksOpen(true)}
          className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
        >
          <span>
            <span className="block text-sm font-medium text-foreground">
              已拉黑
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              查看并管理拉黑列表
            </span>
          </span>
          <ChevronRight
            size={16}
            className="shrink-0 text-muted-foreground"
            aria-hidden
          />
        </button>
      </section>

      <BlockedUsersDialog
        open={blocksOpen}
        onClose={() => setBlocksOpen(false)}
      />
    </div>
  );
}

function SelectOptionRow<T extends string>({
  option,
  selected,
  disabled,
  onSelect,
}: {
  option: OptionRow<T>;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => {
        if (!disabled) onSelect();
      }}
      className={cn(
        "flex w-full cursor-pointer items-start gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left disabled:pointer-events-none disabled:opacity-60",
        selected
          ? "border-primary/40 bg-primary/5"
          : "transition-colors hover:border-primary/40 hover:bg-accent/40",
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-foreground">
          {option.label}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {option.description}
        </span>
      </span>
      {selected && (
        <Check size={16} className="shrink-0 text-primary" aria-hidden />
      )}
    </button>
  );
}
