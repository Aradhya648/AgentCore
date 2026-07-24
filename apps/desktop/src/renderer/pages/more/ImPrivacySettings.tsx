import { Button } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  type DirectorySettings,
  type WhoCanDm,
  getDirectory,
  updateDirectory,
} from "@/services/messaging";
import { Check, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

interface DmOption {
  value: WhoCanDm;
  label: string;
  description: string;
}

const DM_OPTIONS: DmOption[] = [
  {
    value: "anyone",
    label: "任何人",
    description: "可被搜到的用户均可向你发起私信（陌生人首条会进入消息请求）。",
  },
  {
    value: "contacts",
    label: "仅联系人",
    description: "只有你已接受会话的联系人可以向你发起新私信。",
  },
];

/**
 * 消息隐私设置（/more/messages）— discoverability + who-can-DM（消息IM.md §五）。
 *
 * Controls whether others can find you via exact username/ID search and who may
 * open a new DM. Defaults are open (discoverable + anyone); changes persist via
 * PATCH /v1/messages/directory.
 */
export function ImPrivacySettings() {
  const [settings, setSettings] = useState<DirectorySettings | null>(null);
  const [pending, setPending] = useState(false);

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

  return (
    <div>
      <SettingsHeader
        title="消息隐私"
        description="控制他人能否搜到你，以及谁可以向你发起私信。陌生人首条消息会进入消息请求，回复即代表接受。"
      />

      <section className="mt-6 space-y-6">
        <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3">
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
        </div>

        <div>
          <h2 className="text-sm font-medium text-foreground">谁可以私信我</h2>
          <div className="mt-3 space-y-2">
            {DM_OPTIONS.map((option) => (
              <DmOptionRow
                key={option.value}
                option={option}
                selected={settings?.who_can_dm === option.value}
                disabled={settings === null || pending}
                onSelect={() => void patch({ who_can_dm: option.value })}
              />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function DmOptionRow({
  option,
  selected,
  disabled,
  onSelect,
}: {
  option: DmOption;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <Button
      variant="ghost"
      disabled={disabled}
      onClick={onSelect}
      className={`h-auto w-full justify-start gap-3 rounded-xl border px-4 py-3 text-left font-normal ${
        selected
          ? "border-primary/40 bg-primary/5"
          : "border-border bg-card hover:bg-accent"
      }`}
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
    </Button>
  );
}
