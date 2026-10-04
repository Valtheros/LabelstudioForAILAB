import React, { useEffect, useRef } from "react";
import { useAPI } from "../../../providers/ApiProvider";

export const useDraftProject = () => {
  const { callApi } = useAPI();
  const [project, setProject] = React.useState(null);
  const [error, setError] = React.useState("");
  const creating = useRef(false);

  const fetchDraftProject = React.useCallback(async () => {
    if (creating.current) return;
    creating.current = true;
    setError("");
    try {
      const response = await callApi("projects", { errorFilter: () => true });
      if (!response || response.error) throw new Error("Could not load projects. Please retry.");

      const projects = response.results ?? [];
      let projectNumber = projects.length + 1;
      let projectName = `New Project #${projectNumber}`;
      while (projects.find(({ title }) => title === projectName)) {
        projectName = `New Project #${++projectNumber}`;
      }

      const draft = await callApi("createProject", {
        errorFilter: () => true,
        body: { title: projectName, is_draft: true },
      });

      if (!draft?.id) throw new Error("Could not create the project. Please retry.");
      setProject(draft);
    } catch (error) {
      setError(error.message || "Could not create the project. Please retry.");
    } finally {
      creating.current = false;
    }
  }, [callApi]);

  useEffect(() => {
    fetchDraftProject();
  }, [fetchDraftProject]);

  return { project, setProject, error, retry: fetchDraftProject };
};
