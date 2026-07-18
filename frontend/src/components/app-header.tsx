import { Bell, Search, MessageSquare, Settings } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-card/90 px-3 backdrop-blur md:px-5">
      <SidebarTrigger className="h-9 w-9 shrink-0 rounded-lg" />
      <div className="relative hidden flex-1 max-w-md md:block">
        <Search className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="ابحث عن طبيب، تخصص، أو مريض..."
          className="h-9 rounded-lg border-border bg-secondary pr-9 text-[13px] focus-visible:ring-primary"
        />
      </div>
      <div className="flex-1 md:hidden" />
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" className="relative h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground">
          <MessageSquare className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="relative h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground">
          <Bell className="h-4 w-4" />
          <span className="absolute top-1.5 left-1.5 h-1.5 w-1.5 rounded-full bg-destructive ring-2 ring-card" />
        </Button>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground">
          <Settings className="h-4 w-4" />
        </Button>
      </div>
      <div className="mr-1 h-6 w-px bg-border" />
      <div className="flex items-center gap-2.5">
        <div className="hidden text-left md:block">
          <div className="text-[13px] font-semibold leading-tight">محمد الأحمد</div>
          <div className="text-[11px] text-muted-foreground">مريض</div>
        </div>
        <Avatar className="h-9 w-9 ring-2 ring-primary/15">
          <AvatarFallback className="bg-primary text-xs font-semibold text-primary-foreground">
            مأ
          </AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}
